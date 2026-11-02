"""
Integration tests for Techne Dental features:
- Call summary email
- Staff page authentication
- Staff page data isolation
"""
import asyncio
import os
import threading
import time
from datetime import datetime
from email import message_from_bytes
from typing import Optional

import bcrypt
import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Message
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import reload_settings
from app.database import Base, init_db
from app.main import app
from app.models import CallRecord, DemoRequest as DemoRequestModel


class TestMessageHandler:
    """Simple message handler that stores emails."""
    
    def __init__(self):
        self.messages = []
    
    def handle_message(self, message):
        self.messages.append(message)


@pytest.fixture(scope="module")
def smtp_server():
    """Start a test SMTP server in the background."""
    handler = TestMessageHandler()
    controller = Controller(handler, hostname="localhost", port=10025)
    controller.start()
    yield handler
    controller.stop()


@pytest.fixture(scope="function")
def test_db():
    """Create a fresh test database for each test."""
    db_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/test_receptionist"
    )
    
    engine = create_engine(db_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    TestSessionLocal = sessionmaker(bind=engine)
    
    yield TestSessionLocal
    
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db):
    """FastAPI test client with test database."""
    def override_get_db():
        db = test_db()
        try:
            yield db
        finally:
            db.close()
    
    from app.main import get_db
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as c:
        yield c
    
    app.dependency_overrides.clear()


@pytest.fixture
def test_password():
    """Generate a test password and hash."""
    password = "TestPassword123!"
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    return password, password_hash


class TestStaffAuthentication:
    """Test staff page login/logout and rate limiting."""
    
    def test_login_page_loads(self, client):
        """Staff page shows login form when not authenticated."""
        response = client.get("/staff/techne")
        assert response.status_code == 200
        assert "Technē Dental" in response.text
        assert "Staff Login" in response.text
        assert '<input type="password"' in response.text
    
    def test_login_success(self, client, test_password, monkeypatch):
        """Successful login redirects to dashboard."""
        password, password_hash = test_password
        
        monkeypatch.setenv("TECHNE_STAFF_USERNAME", "admin")
        monkeypatch.setenv("TECHNE_STAFF_PASSWORD_HASH", password_hash)
        reload_settings()
        
        response = client.post(
            "/staff/techne/login",
            data={"username": "admin", "password": password},
            follow_redirects=False,
        )
        
        assert response.status_code == 303
        assert response.headers["location"] == "/staff/techne"
        assert "techne_session" in response.cookies
    
    def test_login_failure(self, client, test_password, monkeypatch):
        """Failed login shows error message."""
        _, password_hash = test_password
        
        monkeypatch.setenv("TECHNE_STAFF_USERNAME", "admin")
        monkeypatch.setenv("TECHNE_STAFF_PASSWORD_HASH", password_hash)
        reload_settings()
        
        response = client.post(
            "/staff/techne/login",
            data={"username": "admin", "password": "wrong"},
        )
        
        assert response.status_code == 401
        assert "Invalid username or password" in response.text
    
    def test_rate_limiting(self, client, test_password, monkeypatch):
        """Rate limiting triggers after failed attempts."""
        _, password_hash = test_password
        
        monkeypatch.setenv("TECHNE_STAFF_USERNAME", "admin")
        monkeypatch.setenv("TECHNE_STAFF_PASSWORD_HASH", password_hash)
        reload_settings()
        
        for _ in range(5):
            client.post(
                "/staff/techne/login",
                data={"username": "admin", "password": "wrong"},
            )
        
        response = client.post(
            "/staff/techne/login",
            data={"username": "admin", "password": "wrong"},
        )
        
        assert response.status_code == 429
        assert "Too many failed attempts" in response.text
    
    def test_logout(self, client, test_password, monkeypatch):
        """Logout clears session and redirects."""
        password, password_hash = test_password
        
        monkeypatch.setenv("TECHNE_STAFF_USERNAME", "admin")
        monkeypatch.setenv("TECHNE_STAFF_PASSWORD_HASH", password_hash)
        reload_settings()
        
        login_response = client.post(
            "/staff/techne/login",
            data={"username": "admin", "password": password},
            follow_redirects=True,
        )
        
        response = client.post("/staff/techne/logout", follow_redirects=False)
        
        assert response.status_code == 303
        assert "techne_session" not in response.cookies or response.cookies["techne_session"] == ""


class TestStaffDashboard:
    """Test staff dashboard data isolation and status updates."""
    
    def test_dashboard_shows_only_techne_records(self, client, test_db, test_password, monkeypatch):
        """Dashboard shows only Techne records, not NM2TECH."""
        password, password_hash = test_password
        
        monkeypatch.setenv("TECHNE_STAFF_USERNAME", "admin")
        monkeypatch.setenv("TECHNE_STAFF_PASSWORD_HASH", password_hash)
        reload_settings()
        
        db = test_db()
        
        call1 = CallRecord(call_sid="CA111", caller_phone="+15551234567", business_id="techne_dental")
        call2 = CallRecord(call_sid="CA222", caller_phone="+15559876543", business_id="nm2tech")
        db.add_all([call1, call2])
        db.commit()
        
        techne_request = DemoRequestModel(
            call_sid="CA111",
            caller_name="Jane Doe",
            business_name="",
            caller_phone="+15551234567",
            email="",
            notes="Patient Type: New\\nReason: Checkup\\nInsurance: Aetna",
            status="pending",
            business_id="techne_dental",
        )
        nm2tech_request = DemoRequestModel(
            call_sid="CA222",
            caller_name="John Smith",
            business_name="Smith LLC",
            caller_phone="+15559876543",
            email="john@example.com",
            notes="",
            status="pending",
            business_id="nm2tech",
        )
        db.add_all([techne_request, nm2tech_request])
        db.commit()
        db.close()
        
        client.post(
            "/staff/techne/login",
            data={"username": "admin", "password": password},
        )
        
        response = client.get("/staff/techne")
        
        assert response.status_code == 200
        assert "Jane Doe" in response.text
        assert "John Smith" not in response.text
        assert "techne_dental" not in response.text.lower()
        assert "nm2tech" not in response.text.lower()
    
    def test_status_update_persists(self, client, test_db, test_password, monkeypatch):
        """Status update persists to database."""
        password, password_hash = test_password
        
        monkeypatch.setenv("TECHNE_STAFF_USERNAME", "admin")
        monkeypatch.setenv("TECHNE_STAFF_PASSWORD_HASH", password_hash)
        reload_settings()
        
        db = test_db()
        
        call = CallRecord(call_sid="CA333", caller_phone="+15551111111", business_id="techne_dental")
        db.add(call)
        db.commit()
        
        request = DemoRequestModel(
            call_sid="CA333",
            caller_name="Test User",
            business_name="",
            caller_phone="+15551111111",
            email="",
            notes="Test notes",
            status="pending",
            business_id="techne_dental",
        )
        db.add(request)
        db.commit()
        request_id = request.id
        db.close()
        
        client.post(
            "/staff/techne/login",
            data={"username": "admin", "password": password},
        )
        
        response = client.post(
            f"/staff/techne/requests/{request_id}/status",
            data={"status": "confirmed"},
            follow_redirects=False,
        )
        
        assert response.status_code == 303
        
        db = test_db()
        updated = db.query(DemoRequestModel).filter_by(id=request_id).first()
        assert updated.status == "confirmed"
        db.close()


class TestEmailSummary:
    """Test call summary email delivery."""
    
    def test_email_sent_on_appointment_complete(self, client, smtp_server, test_db, monkeypatch):
        """Email is sent when Techne appointment is saved."""
        smtp_server.messages.clear()
        
        monkeypatch.setenv("SMTP_HOST", "localhost")
        monkeypatch.setenv("SMTP_PORT", "10025")
        monkeypatch.setenv("SMTP_USERNAME", "test")
        monkeypatch.setenv("SMTP_PASSWORD", "test")
        monkeypatch.setenv("SMTP_FROM", "receptionist@example.com")
        monkeypatch.setenv("TECHNE_MESSAGE_EMAIL", "staff@techne.example")
        monkeypatch.setenv("TWILIO_VALIDATE_REQUESTS", "false")
        reload_settings()
        
        db = test_db()
        call = CallRecord(
            call_sid="CA444",
            caller_phone="+15552222222",
            business_id="techne_dental",
            flow="taking_demo",
            flow_state='{"name":"Alice","phone":"+15552222222","new_or_existing":"New","reason":"Checkup","insurance":"BlueCross","preferred_times":"Morning"}',
        )
        db.add(call)
        db.commit()
        db.close()
        
        response = client.post(
            "/twilio/gather",
            data={
                "CallSid": "CA444",
                "From": "+15552222222",
                "To": "+13014508797",
                "SpeechResult": "Morning appointments work best for me",
            },
        )
        
        assert response.status_code == 200
        
        time.sleep(1)
        
        assert len(smtp_server.messages) >= 1
        email = smtp_server.messages[-1]
        
        body = str(email)
        
        assert "Alice" in body
        assert "+15552222222" in body or "5552222222" in body
        assert "New" in body
        assert "Checkup" in body
        assert "BlueCross" in body
        assert "Morning" in body or "morning" in body
    
    def test_email_not_sent_for_nm2tech(self, client, smtp_server, test_db, monkeypatch):
        """Email is NOT sent for NM2TECH calls."""
        smtp_server.messages.clear()
        
        monkeypatch.setenv("SMTP_HOST", "localhost")
        monkeypatch.setenv("SMTP_PORT", "10025")
        monkeypatch.setenv("SMTP_USERNAME", "test")
        monkeypatch.setenv("SMTP_PASSWORD", "test")
        monkeypatch.setenv("SMTP_FROM", "receptionist@example.com")
        monkeypatch.setenv("TWILIO_VALIDATE_REQUESTS", "false")
        reload_settings()
        
        db = test_db()
        call = CallRecord(
            call_sid="CA555",
            caller_phone="+15553333333",
            business_id="nm2tech",
            flow="taking_demo",
            flow_state='{"name":"Bob","business_name":"Bob LLC","phone":"+15553333333","email":"bob@example.com"}',
        )
        db.add(call)
        db.commit()
        db.close()
        
        response = client.post(
            "/twilio/gather",
            data={
                "CallSid": "CA555",
                "From": "+15553333333",
                "To": "+12408081048",
                "SpeechResult": "Tomorrow afternoon",
            },
        )
        
        assert response.status_code == 200
        
        initial_count = len(smtp_server.messages)
        time.sleep(1)
        
        assert len(smtp_server.messages) == initial_count
    
    def test_call_succeeds_when_smtp_fails(self, client, test_db, monkeypatch):
        """Call still returns TwiML even when SMTP is down."""
        monkeypatch.setenv("SMTP_HOST", "invalid-smtp-host.example")
        monkeypatch.setenv("SMTP_PORT", "9999")
        monkeypatch.setenv("SMTP_USERNAME", "test")
        monkeypatch.setenv("SMTP_PASSWORD", "test")
        monkeypatch.setenv("SMTP_FROM", "receptionist@example.com")
        monkeypatch.setenv("TECHNE_MESSAGE_EMAIL", "staff@techne.example")
        monkeypatch.setenv("TWILIO_VALIDATE_REQUESTS", "false")
        reload_settings()
        
        db = test_db()
        call = CallRecord(
            call_sid="CA666",
            caller_phone="+15554444444",
            business_id="techne_dental",
            flow="taking_demo",
            flow_state='{"name":"Charlie","phone":"+15554444444","new_or_existing":"Existing","reason":"Filling","insurance":"None","preferred_times":"Afternoon"}',
        )
        db.add(call)
        db.commit()
        db.close()
        
        response = client.post(
            "/twilio/gather",
            data={
                "CallSid": "CA666",
                "From": "+15554444444",
                "To": "+13014508797",
                "SpeechResult": "Afternoon",
            },
        )
        
        assert response.status_code == 200
        assert b"<Response>" in response.content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
