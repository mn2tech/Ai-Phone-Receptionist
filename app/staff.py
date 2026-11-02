"""
Staff authentication and portal routes for Techne Dental.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Response, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import reload_settings
from app.database import SessionLocal
from app.encryption import decrypt_field
from app.models import DemoRequest as DemoRequestModel

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory session store and rate limiting
active_sessions = {}  # {session_token: timestamp}
login_attempts = defaultdict(list)  # {ip: [timestamp, ...]}

SESSION_DURATION = timedelta(hours=8)
MAX_LOGIN_ATTEMPTS = 5
RATE_LIMIT_WINDOW = timedelta(minutes=15)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a password against a hash (bcrypt or pbkdf2)."""
    if password_hash.startswith("$2"):  # bcrypt format
        try:
            import bcrypt
            return bcrypt.checkpw(plain_password.encode(), password_hash.encode())
        except ImportError:
            logger.error("bcrypt not installed but bcrypt hash detected")
            return False
    elif ":" in password_hash:  # pbkdf2 format: algorithm:iterations:salt:hash
        try:
            parts = password_hash.split(":")
            if len(parts) != 4:
                return False
            algorithm, iterations, salt_hex, stored_hash = parts
            computed_hash = hashlib.pbkdf2_hmac(
                algorithm,
                plain_password.encode(),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
            return computed_hash.hex() == stored_hash
        except Exception as e:
            logger.error(f"pbkdf2 verification failed: {e}")
            return False
    return False


def is_rate_limited(ip: str) -> bool:
    """Check if an IP is rate limited."""
    now = datetime.now()
    cutoff = now - RATE_LIMIT_WINDOW
    login_attempts[ip] = [ts for ts in login_attempts[ip] if ts > cutoff]
    return len(login_attempts[ip]) >= MAX_LOGIN_ATTEMPTS


def record_login_attempt(ip: str):
    """Record a failed login attempt."""
    login_attempts[ip].append(datetime.now())


def create_session(response: Response) -> str:
    """Create a new session and set cookie."""
    session_token = secrets.token_urlsafe(32)
    active_sessions[session_token] = datetime.now()
    response.set_cookie(
        key="techne_session",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=int(SESSION_DURATION.total_seconds()),
    )
    return session_token


def verify_session(request: Request) -> bool:
    """Verify a session token is valid."""
    session_token = request.cookies.get("techne_session")
    if not session_token or session_token not in active_sessions:
        return False
    
    session_time = active_sessions[session_token]
    if datetime.now() - session_time > SESSION_DURATION:
        del active_sessions[session_token]
        return False
    
    return True


def require_auth(request: Request):
    """Dependency to require authentication."""
    if not verify_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/staff/techne", response_class=HTMLResponse)
async def staff_page(request: Request, db: Session = Depends(get_db)):
    """Techne staff dashboard - show login or data."""
    if not verify_session(request):
        return _render_login_page()
    
    # Fetch Techne records only
    records = (
        db.query(DemoRequestModel)
        .filter(DemoRequestModel.business_id == "techne_dental")
        .order_by(DemoRequestModel.created_at.desc())
        .all()
    )
    
    # Decrypt fields
    decrypted_records = []
    for record in records:
        db.expunge(record)
        decrypted = {
            "id": record.id,
            "created_at": record.created_at,
            "caller_name": decrypt_field(record.caller_name),
            "caller_phone": decrypt_field(record.caller_phone),
            "business_name": decrypt_field(record.business_name),
            "email": decrypt_field(record.email) if record.email else "",
            "notes": decrypt_field(record.notes) if record.notes else "",
            "status": record.status or "pending",
        }
        decrypted_records.append(decrypted)
    
    return _render_dashboard_page(decrypted_records)


@router.post("/staff/techne/login")
async def staff_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Handle staff login."""
    client_ip = request.client.host if request.client else "unknown"
    
    if is_rate_limited(client_ip):
        return HTMLResponse(
            _render_login_page(error="Too many failed attempts. Try again in 15 minutes."),
            status_code=429,
        )
    
    cfg = reload_settings()
    if not cfg.techne_staff_password_hash:
        return HTMLResponse(
            _render_login_page(error="Authentication not configured."),
            status_code=500,
        )
    
    if (
        username == cfg.techne_staff_username
        and verify_password(password, cfg.techne_staff_password_hash)
    ):
        response = RedirectResponse(url="/staff/techne", status_code=303)
        create_session(response)
        return response
    
    record_login_attempt(client_ip)
    return HTMLResponse(
        _render_login_page(error="Invalid username or password."),
        status_code=401,
    )


@router.post("/staff/techne/logout")
async def staff_logout(request: Request):
    """Handle staff logout."""
    session_token = request.cookies.get("techne_session")
    if session_token and session_token in active_sessions:
        del active_sessions[session_token]
    
    response = RedirectResponse(url="/staff/techne", status_code=303)
    response.delete_cookie("techne_session")
    return response


@router.post("/staff/techne/requests/{request_id}/status")
async def update_request_status(
    request_id: int,
    status: str = Form(...),
    request: Request = None,
    db: Session = Depends(get_db),
    _auth: None = Depends(require_auth),
):
    """Update the status of a request."""
    if status not in ["pending", "confirmed", "done"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    record = (
        db.query(DemoRequestModel)
        .filter(
            DemoRequestModel.id == request_id,
            DemoRequestModel.business_id == "techne_dental",
        )
        .first()
    )
    
    if not record:
        raise HTTPException(status_code=404, detail="Request not found")
    
    record.status = status
    db.commit()
    
    return RedirectResponse(url="/staff/techne", status_code=303)


def _render_login_page(error: Optional[str] = None) -> str:
    """Render the login page."""
    error_html = ""
    if error:
        error_html = f'<div style="color: #d32f2f; margin-bottom: 1rem; padding: 0.75rem; background: #ffebee; border-radius: 4px;">{error}</div>'
    
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Technē Dental — Staff Login</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1rem;
        }}
        .login-card {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            padding: 2rem;
            width: 100%;
            max-width: 400px;
        }}
        h1 {{
            font-size: 1.75rem;
            margin-bottom: 0.5rem;
            color: #1a202c;
        }}
        p {{
            color: #718096;
            margin-bottom: 2rem;
            font-size: 0.875rem;
        }}
        label {{
            display: block;
            font-weight: 500;
            margin-bottom: 0.5rem;
            color: #4a5568;
            font-size: 0.875rem;
        }}
        input {{
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            font-size: 1rem;
            margin-bottom: 1rem;
        }}
        input:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }}
        button {{
            width: 100%;
            padding: 0.75rem;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 1rem;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }}
        button:hover {{
            background: #5568d3;
        }}
    </style>
</head>
<body>
    <div class="login-card">
        <h1>Technē Dental</h1>
        <p>Call Requests — Staff Login</p>
        {error_html}
        <form method="post" action="/staff/techne/login">
            <label>Username</label>
            <input type="text" name="username" required autocomplete="username">
            
            <label>Password</label>
            <input type="password" name="password" required autocomplete="current-password">
            
            <button type="submit">Sign In</button>
        </form>
    </div>
</body>
</html>
"""


def _render_dashboard_page(records: list) -> str:
    """Render the dashboard page."""
    if not records:
        records_html = '<p style="text-align: center; color: #718096; padding: 2rem;">No requests yet.</p>'
    else:
        records_html = '<div class="records">'
        for record in records:
            created_at = record["created_at"]
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=ZoneInfo("UTC"))
            et_time = created_at.astimezone(ZoneInfo("America/New_York"))
            time_str = et_time.strftime("%b %d, %Y at %I:%M %p %Z")
            
            status = record["status"]
            status_colors = {
                "pending": "#fbbf24",
                "confirmed": "#3b82f6",
                "done": "#10b981",
            }
            status_color = status_colors.get(status, "#6b7280")
            
            notes_lines = (record.get("notes") or "").split("\n")
            notes_html = "<br>".join(notes_lines) if notes_lines else "<em>No details</em>"
            
            records_html += f"""
            <div class="record">
                <div class="record-header">
                    <div>
                        <strong>{record["caller_name"] or "Unknown"}</strong>
                        <div style="color: #718096; font-size: 0.875rem;">{time_str}</div>
                    </div>
                    <div class="status-badge" style="background-color: {status_color};">{status.upper()}</div>
                </div>
                <div class="record-body">
                    <p><strong>Phone:</strong> {record["caller_phone"] or "Not provided"}</p>
                    <p><strong>Details:</strong> {notes_html}</p>
                </div>
                <form method="post" action="/staff/techne/requests/{record["id"]}/status" class="status-form">
                    <select name="status">
                        <option value="pending" {"selected" if status == "pending" else ""}>Pending</option>
                        <option value="confirmed" {"selected" if status == "confirmed" else ""}>Confirmed</option>
                        <option value="done" {"selected" if status == "done" else ""}>Done</option>
                    </select>
                    <button type="submit">Update</button>
                </form>
            </div>
            """
        records_html += '</div>'
    
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Technē Dental — Call Requests</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
            padding-bottom: 2rem;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .header-content {{
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        h1 {{
            font-size: 1.5rem;
        }}
        .logout-btn {{
            background: rgba(255,255,255,0.2);
            border: 1px solid rgba(255,255,255,0.3);
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.875rem;
        }}
        .logout-btn:hover {{
            background: rgba(255,255,255,0.3);
        }}
        .container {{
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 1rem;
        }}
        .records {{
            display: grid;
            gap: 1rem;
        }}
        .record {{
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .record-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid #e2e8f0;
        }}
        .status-badge {{
            color: white;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .record-body {{
            margin-bottom: 1rem;
            line-height: 1.6;
        }}
        .record-body p {{
            margin-bottom: 0.5rem;
            color: #4a5568;
        }}
        .status-form {{
            display: flex;
            gap: 0.5rem;
        }}
        .status-form select {{
            flex: 1;
            padding: 0.5rem;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            font-size: 0.875rem;
        }}
        .status-form button {{
            padding: 0.5rem 1rem;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.875rem;
        }}
        .status-form button:hover {{
            background: #5568d3;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <h1>Technē Dental — Call Requests</h1>
            <form method="post" action="/staff/techne/logout" style="margin: 0;">
                <button type="submit" class="logout-btn">Sign Out</button>
            </form>
        </div>
    </div>
    <div class="container">
        {records_html}
    </div>
</body>
</html>
"""
