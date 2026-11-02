#!/usr/bin/env python3
"""
Quick smoke tests for Techne features.
"""
import os
import sys

# Set test environment
os.environ["ENCRYPTION_KEY"] = ""
os.environ["DATABASE_URL"] = "sqlite:///test_smoke.db"
os.environ["TWILIO_VALIDATE_REQUESTS"] = "false"
os.environ["TECHNE_STAFF_USERNAME"] = "admin"
os.environ["TECHNE_STAFF_PASSWORD_HASH"] = "$2b$12$test"

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, SessionLocal, engine

# Initialize database
Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_health():
    """Test health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    print("✓ Health endpoint works")

def test_login_page():
    """Test staff login page loads."""
    response = client.get("/staff/techne")
    assert response.status_code == 200
    assert "Technē Dental" in response.text
    print("✓ Staff login page loads")

def test_email_service_import():
    """Test email service imports."""
    from app.email_service import is_smtp_configured, send_call_summary_email
    assert not is_smtp_configured()
    print("✓ Email service imports and checks config")

def test_password_script_exists():
    """Test password hash script exists."""
    import os.path
    assert os.path.exists("scripts/generate_password_hash.py")
    print("✓ Password hash script exists")

if __name__ == "__main__":
    try:
        test_health()
        test_login_page()
        test_email_service_import()
        test_password_script_exists()
        print("\n✅ All smoke tests passed!")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
