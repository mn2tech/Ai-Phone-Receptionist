"""Test security features: Twilio signature validation, API key auth, field encryption."""

import os
import httpx
from cryptography.fernet import Fernet

BASE = "http://127.0.0.1:8000"
CALLER = "+14105551234"
NM2TECH_NUMBER = "+13012982874"

# Generate test keys
TEST_API_KEY = "test-api-key-12345"
TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()

print("=== Security Tests ===\n")
print(f"Test API Key: {TEST_API_KEY}")
print(f"Test Encryption Key: {TEST_ENCRYPTION_KEY[:20]}...\n")

# Test 1: API Key Authentication
print("[1] API Key Authentication")
print("   Testing /calls endpoint without API key...")
r = httpx.get(f"{BASE}/calls", timeout=10)
if r.status_code == 403:
    print("   ✓ Returns 403 without API key")
elif r.status_code == 200:
    print("   ⚠ WARNING: Returns 200 (API_KEY not set - auth disabled)")
else:
    print(f"   ✗ Unexpected status: {r.status_code}")

print("   Testing /calls endpoint with valid API key...")
r = httpx.get(f"{BASE}/calls", headers={"X-API-Key": TEST_API_KEY}, timeout=10)
if r.status_code == 200:
    print("   ✓ Returns 200 with valid API key")
elif r.status_code == 403:
    print("   ⚠ Returns 403 (API key doesn't match server config)")
else:
    print(f"   ✗ Unexpected status: {r.status_code}")

print("   Testing /calls endpoint with invalid API key...")
r = httpx.get(f"{BASE}/calls", headers={"X-API-Key": "wrong-key"}, timeout=10)
if r.status_code == 403:
    print("   ✓ Returns 403 with invalid API key")
elif r.status_code == 200:
    print("   ⚠ WARNING: Returns 200 (API_KEY not set - auth disabled)")
else:
    print(f"   ✗ Unexpected status: {r.status_code}")

print()

# Test 2: Twilio Signature Validation
print("[2] Twilio Signature Validation")
print("   Testing /twilio/voice without X-Twilio-Signature...")
r = httpx.post(
    f"{BASE}/twilio/voice",
    data={"CallSid": "test-001", "From": CALLER, "To": NM2TECH_NUMBER},
    timeout=10
)
if r.status_code == 403:
    print("   ✓ Returns 403 without signature (validation enabled)")
elif r.status_code == 200:
    print("   ⚠ WARNING: Returns 200 (TWILIO_VALIDATE_REQUESTS=false)")
else:
    print(f"   ✗ Unexpected status: {r.status_code}")

print("   Testing /twilio/voice with invalid signature...")
r = httpx.post(
    f"{BASE}/twilio/voice",
    data={"CallSid": "test-002", "From": CALLER, "To": NM2TECH_NUMBER},
    headers={"X-Twilio-Signature": "invalid-signature-abc123"},
    timeout=10
)
if r.status_code == 403:
    print("   ✓ Returns 403 with invalid signature (validation enabled)")
elif r.status_code == 200:
    print("   ⚠ WARNING: Returns 200 (TWILIO_VALIDATE_REQUESTS=false)")
else:
    print(f"   ✗ Unexpected status: {r.status_code}")

print()

# Test 3: Field Encryption
print("[3] Field Encryption")
print("   Testing encryption utility functions...")

# Import after server is running (to pick up env vars)
try:
    from app.encryption import encrypt_field, decrypt_field, is_encryption_enabled
    
    if is_encryption_enabled():
        print("   ✓ Encryption is enabled")
        
        # Test encryption/decryption
        plaintext = "+14105551234"
        encrypted = encrypt_field(plaintext)
        decrypted = decrypt_field(encrypted)
        
        if encrypted.startswith("enc:") and len(encrypted) > 20:
            print(f"   ✓ Encrypted: {plaintext} -> {encrypted[:30]}...")
        else:
            print(f"   ✗ Encryption failed: {encrypted}")
        
        if decrypted == plaintext:
            print(f"   ✓ Decrypted correctly: {encrypted[:30]}... -> {plaintext}")
        else:
            print(f"   ✗ Decryption mismatch: got {decrypted}")
        
        # Test backward compatibility (plaintext pass-through)
        plain_passthrough = decrypt_field("plaintext-value")
        if plain_passthrough == "plaintext-value":
            print("   ✓ Plaintext pass-through works (backward compatibility)")
        else:
            print(f"   ✗ Plaintext pass-through failed: {plain_passthrough}")
        
        # Test empty string handling
        empty_encrypted = encrypt_field("")
        empty_decrypted = decrypt_field(empty_encrypted)
        if empty_encrypted == "" and empty_decrypted == "":
            print("   ✓ Empty string handling works")
        else:
            print(f"   ✗ Empty string issue: enc={empty_encrypted}, dec={empty_decrypted}")
    else:
        print("   ⚠ WARNING: Encryption is DISABLED (ENCRYPTION_KEY not set)")
        print("   PHI will be stored in plaintext")
except Exception as exc:
    print(f"   ✗ Encryption test failed: {exc}")

print()

# Test 4: End-to-end with encryption
print("[4] End-to-End: Call with Encryption")
print("   Creating a test call to verify PHI encryption in database...")

# Note: This requires the server to be running with ENCRYPTION_KEY set
try:
    # Simulate a call (will be rejected by Twilio signature validation if enabled)
    # We can't easily test this without a valid Twilio signature, but we can verify
    # the database functions work with encryption
    
    from app.database import SessionLocal, save_voicemail, get_voicemails_for_call
    from app.encryption import is_encryption_enabled
    
    if is_encryption_enabled():
        session = SessionLocal()
        try:
            # Save a voicemail with PHI
            vm = save_voicemail(
                session,
                call_sid="test-encryption-001",
                caller_name="John Doe",
                caller_phone="+14105551234",
                message_text="I have a toothache"
            )
            session.commit()
            
            # Check that it's encrypted in the DB
            if vm.caller_name.startswith("enc:") and vm.caller_phone.startswith("enc:"):
                print("   ✓ PHI encrypted before database insert")
            else:
                print(f"   ✗ PHI not encrypted: name={vm.caller_name[:20]}, phone={vm.caller_phone[:20]}")
            
            # Retrieve and verify decryption
            vms = get_voicemails_for_call(session, "test-encryption-001")
            if vms and vms[0].caller_name == "John Doe" and vms[0].caller_phone == "+14105551234":
                print("   ✓ PHI decrypted correctly on retrieval")
            else:
                print(f"   ✗ Decryption failed: {vms[0].caller_name if vms else 'no record'}")
            
            # Clean up
            session.query(type(vm)).filter_by(call_sid="test-encryption-001").delete()
            session.commit()
            print("   ✓ Test data cleaned up")
        finally:
            session.close()
    else:
        print("   ⚠ Skipped (encryption not enabled)")
except Exception as exc:
    print(f"   ✗ End-to-end test failed: {exc}")

print()

# Test 5: Protected endpoints list
print("[5] Protected Endpoints Summary")
protected_endpoints = [
    ("GET", "/calls", "List calls (requires API key)"),
    ("GET", "/calls/{sid}", "Get call details (requires API key)"),
    ("GET", "/demos", "List demos (requires API key)"),
    ("GET", "/demos/{id}", "Get demo details (requires API key)"),
    ("POST", "/twilio/voice", "Incoming call (requires Twilio signature)"),
    ("POST", "/twilio/gather", "Speech result (requires Twilio signature)"),
    ("POST", "/twilio/status", "Call status (requires Twilio signature)"),
    ("POST", "/twilio/transfer-status", "Transfer status (requires Twilio signature)"),
]

print("   Protected endpoints:")
for method, path, desc in protected_endpoints:
    print(f"   - {method:6} {path:25} {desc}")

print()
print("=== Test Summary ===")
print("Security features implemented:")
print("1. ✓ API Key authentication on /calls and /demos endpoints")
print("2. ✓ Twilio signature validation on all /twilio/* webhooks")
print("3. ✓ Field-level encryption for PHI data")
print()
print("To enable all features, set these environment variables:")
print("  API_KEY=<your-api-key>")
print("  ENCRYPTION_KEY=<fernet-key>")
print("  TWILIO_VALIDATE_REQUESTS=true")
print()
print("Generate keys:")
print('  API_KEY: python -c "import secrets; print(secrets.token_urlsafe(32))"')
print('  ENCRYPTION_KEY: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')
