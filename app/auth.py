"""Authentication and authorization for API endpoints."""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Header, Request, status
from twilio.request_validator import RequestValidator

from app.config import reload_settings

logger = logging.getLogger(__name__)


async def verify_api_key(x_api_key: Annotated[str, Header()] = "") -> None:
    """
    Verify API key for protected endpoints.
    
    Raises 403 if API key is required and invalid.
    If API_KEY is not set in config, authentication is disabled (logs a warning).
    """
    cfg = reload_settings()
    expected_key = (cfg.api_key or "").strip()
    
    # If no API key configured, allow unauthenticated access (log warning)
    if not expected_key:
        logger.warning("API_KEY not set - endpoint accessible without authentication")
        return
    
    # Check API key
    provided_key = (x_api_key or "").strip()
    if not provided_key or provided_key != expected_key:
        logger.warning("Invalid API key attempt: %s", provided_key[:8] if provided_key else "[empty]")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key. Provide X-API-Key header.",
        )


async def validate_twilio_signature(request: Request) -> None:
    """
    Verify Twilio request signature to prevent webhook forgery.
    
    Validates X-Twilio-Signature header using TWILIO_AUTH_TOKEN.
    Handles proxies correctly by checking X-Forwarded-Proto for HTTPS.
    
    Raises 403 if signature validation is enabled and signature is invalid.
    Can be disabled with TWILIO_VALIDATE_REQUESTS=false (local testing only).
    """
    cfg = reload_settings()
    
    # Allow disabling validation for local testing (not recommended in production)
    if not cfg.twilio_validate_requests:
        logger.warning("Twilio signature validation is DISABLED")
        return
    
    # Get signature from header
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        logger.error("Missing X-Twilio-Signature header")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing Twilio signature",
        )
    
    # Get Twilio auth token
    auth_token = (cfg.twilio_auth_token or "").strip()
    if not auth_token:
        logger.error("TWILIO_AUTH_TOKEN not configured - cannot validate signatures")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Twilio auth token not configured",
        )
    
    # Build the URL Twilio used to compute the signature
    # Important: Railway/Render use HTTPS but forward as HTTP internally,
    # so we need to check X-Forwarded-Proto to reconstruct the correct URL
    url = str(request.url)
    
    # Handle proxy/load balancer (Railway, Render, ngrok)
    proto = request.headers.get("X-Forwarded-Proto", "")
    if proto == "https" and url.startswith("http://"):
        # Replace http:// with https:// to match what Twilio signed
        url = "https://" + url[7:]
    
    # Get POST parameters (form data)
    form_data = await request.form()
    params = dict(form_data)
    
    # Validate signature
    validator = RequestValidator(auth_token)
    is_valid = validator.validate(url, params, signature)
    
    if not is_valid:
        logger.error(
            "Invalid Twilio signature: url=%s signature=%s...",
            url,
            signature[:20],
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature",
        )
    
    logger.debug("Twilio signature validated successfully")
