"""
Email service for sending call summaries.
"""
import smtplib
import logging
from email.message import EmailMessage
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import reload_settings

logger = logging.getLogger(__name__)


def is_smtp_configured() -> bool:
    """Check if SMTP is properly configured."""
    cfg = reload_settings()
    return bool(
        cfg.smtp_host
        and cfg.smtp_username
        and cfg.smtp_password
        and cfg.smtp_from
    )


async def send_call_summary_email(
    caller_name: str,
    caller_phone: str,
    patient_type: Optional[str],
    reason: Optional[str],
    insurance: Optional[str],
    preferred_times: Optional[str],
    urgency: Optional[str],
    call_time: datetime,
    staff_page_url: str = "https://your-domain.com/staff/techne",
) -> bool:
    """
    Send a call summary email for Techne Dental.
    
    Returns True if sent successfully, False otherwise.
    Never raises exceptions - failures are logged and returned as False.
    """
    if not is_smtp_configured():
        logger.warning(
            "SMTP not configured - skipping email. "
            "Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM."
        )
        return False

    cfg = reload_settings()
    recipients = [email.strip() for email in cfg.techne_message_email.split(",") if email.strip()]
    if not recipients:
        logger.warning("No email recipients configured in TECHNE_MESSAGE_EMAIL.")
        return False

    try:
        # Format timestamp in Eastern Time
        et_time = call_time.astimezone(ZoneInfo("America/New_York"))
        time_str = et_time.strftime("%B %d, %Y at %I:%M %p %Z")

        # Build email content
        msg = EmailMessage()
        msg["Subject"] = f"New Call Request - {caller_name or 'Unknown Caller'}"
        msg["From"] = cfg.smtp_from
        msg["To"] = ", ".join(recipients)

        # Build body
        body_lines = [
            f"New call request received on {time_str}",
            "",
            f"Caller: {caller_name or 'Not provided'}",
            f"Phone: {caller_phone or 'Not provided'}",
            f"Patient Type: {patient_type or 'Not provided'}",
            f"Reason: {reason or 'Not provided'}",
            f"Insurance: {insurance or 'Not provided'}",
            f"Preferred Times: {preferred_times or 'Not provided'}",
        ]
        
        if urgency:
            body_lines.insert(1, f"⚠️ URGENT: {urgency}")
            body_lines.insert(2, "")

        body_lines.extend([
            "",
            f"View and manage this request: {staff_page_url}",
            "",
            "—",
            "Technē Dental AI Receptionist",
        ])

        msg.set_content("\n".join(body_lines))

        # Send via SMTP
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as server:
            server.starttls()
            server.login(cfg.smtp_username, cfg.smtp_password)
            server.send_message(msg)

        logger.info(f"Call summary email sent to {len(recipients)} recipient(s)")
        return True

    except Exception as e:
        logger.error(f"Failed to send call summary email: {type(e).__name__}")
        return False
