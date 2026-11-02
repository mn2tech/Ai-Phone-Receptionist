"""Test multi-tenant business routing and behavior."""

import httpx

BASE = "http://127.0.0.1:8000"

# Test phone numbers
NM2TECH_NUMBER = "+13012982874"
TECHNE_NUMBER = "+15555551234"
CALLER = "+14105551234"

print("=== Multi-Tenant Routing Tests ===\n")

# Test 1: NM2TECH greeting (no AI disclosure)
print("[1] NM2TECH greeting (default behavior)")
r = httpx.post(
    f"{BASE}/twilio/voice",
    data={"CallSid": "test-nm2tech-001", "From": CALLER, "To": NM2TECH_NUMBER},
    timeout=30
)
has_nm2tech = "NM2TECH" in r.text
has_ai_disclosure = "AI assistant" in r.text or "artificial intelligence" in r.text.lower()
print(f"   Status: {r.status_code}")
print(f"   NM2TECH branding: {has_nm2tech}")
print(f"   AI disclosure: {has_ai_disclosure} (should be False)")
print()

# Test 2: Techne Dental greeting (with AI disclosure)
print("[2] Techne Dental greeting (AI disclosure required)")
r = httpx.post(
    f"{BASE}/twilio/voice",
    data={"CallSid": "test-techne-001", "From": CALLER, "To": TECHNE_NUMBER},
    timeout=30
)
has_techne = "Technē Dental" in r.text or "Techne Dental" in r.text
has_ai_disclosure = "AI assistant" in r.text
print(f"   Status: {r.status_code}")
print(f"   Techne branding: {has_techne}")
print(f"   AI disclosure: {has_ai_disclosure} (should be True)")
print()

# Test 3: NM2TECH conversation flow (products/pricing)
print("[3] NM2TECH conversation (pricing FAQ)")
r = httpx.post(
    f"{BASE}/twilio/gather",
    data={
        "CallSid": "test-nm2tech-001",
        "From": CALLER,
        "To": NM2TECH_NUMBER,
        "SpeechResult": "What are your prices?"
    },
    timeout=30
)
has_pricing = "99" in r.text or "ninety-nine" in r.text.lower()
print(f"   Status: {r.status_code}")
print(f"   Pricing response: {has_pricing} (should be True for NM2TECH)")
print()

# Test 4: Techne conversation (insurance question)
print("[4] Techne Dental conversation (insurance inquiry)")
r = httpx.post(
    f"{BASE}/twilio/gather",
    data={
        "CallSid": "test-techne-001",
        "From": CALLER,
        "To": TECHNE_NUMBER,
        "SpeechResult": "Do you take CareFirst insurance?"
    },
    timeout=30
)
has_insurance_response = "CareFirst" in r.text or "accepted" in r.text.lower() or "insurance" in r.text.lower()
has_techne_context = "office" in r.text.lower() or "team" in r.text.lower()
print(f"   Status: {r.status_code}")
print(f"   Insurance response: {has_insurance_response}")
print(f"   Techne context: {has_techne_context}")
print()

# Test 5: Techne emergency (should not give pricing/NM2TECH info)
print("[5] Techne Dental emergency scenario")
r = httpx.post(
    f"{BASE}/twilio/gather",
    data={
        "CallSid": "test-techne-002",
        "From": CALLER,
        "To": TECHNE_NUMBER,
        "SpeechResult": "I have a severe toothache"
    },
    timeout=30
)
has_emergency_response = any(w in r.text.lower() for w in ["pain", "help", "soon", "office", "call back"])
has_nm2tech = "NM2TECH" in r.text or "nm2tech" in r.text.lower()
print(f"   Status: {r.status_code}")
print(f"   Emergency handling: {has_emergency_response}")
print(f"   No NM2TECH bleed: {not has_nm2tech} (should be True)")
print()

# Test 6: NM2TECH transfer request (Michael)
print("[6] NM2TECH transfer to owner")
r = httpx.post(
    f"{BASE}/twilio/gather",
    data={
        "CallSid": "test-nm2tech-002",
        "From": CALLER,
        "To": NM2TECH_NUMBER,
        "SpeechResult": "I want to talk to Michael"
    },
    timeout=30
)
has_transfer = "connecting" in r.text.lower() or "<Dial>" in r.text
has_michael = "Michael" in r.text
print(f"   Status: {r.status_code}")
print(f"   Transfer initiated: {has_transfer}")
print(f"   Michael mentioned: {has_michael}")
print()

# Test 7: Techne booking request (should be request-only, not live calendar)
print("[7] Techne appointment request (request-only mode)")
r = httpx.post(
    f"{BASE}/twilio/gather",
    data={
        "CallSid": "test-techne-003",
        "From": CALLER,
        "To": TECHNE_NUMBER,
        "SpeechResult": "I'd like to schedule a cleaning"
    },
    timeout=30
)
is_collecting_name = "name" in r.text.lower()
has_no_slots = "slot" not in r.text.lower() and "available" not in r.text.lower()
print(f"   Status: {r.status_code}")
print(f"   Collecting info: {is_collecting_name}")
print(f"   Not showing slots: {has_no_slots} (Techne = request-only)")
print()

print("=== Test Summary ===")
print("All tests should show expected behavior:")
print("- NM2TECH: no AI disclosure, has pricing, can transfer to Michael")
print("- Techne: AI disclosure required, dental context, request-only booking")
