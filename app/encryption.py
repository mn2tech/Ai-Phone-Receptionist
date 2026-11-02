"""Field-level encryption for PHI data.

Uses Fernet symmetric encryption (AES-128 in CBC mode with HMAC authentication).
Encryption key must be stored in ENCRYPTION_KEY environment variable (32 bytes, base64-encoded).

Generate a key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import base64
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import reload_settings

logger = logging.getLogger(__name__)

_fernet: Optional[Fernet] = None


def _get_fernet() -> Optional[Fernet]:
    """Return Fernet cipher instance, or None if encryption is disabled."""
    global _fernet
    
    if _fernet is not None:
        return _fernet
    
    cfg = reload_settings()
    key = (cfg.encryption_key or "").strip()
    
    if not key:
        return None
    
    try:
        _fernet = Fernet(key.encode())
        return _fernet
    except Exception as exc:
        logger.error("Invalid ENCRYPTION_KEY: %s", exc)
        return None


def encrypt_field(plaintext: str) -> str:
    """
    Encrypt a string field for database storage.
    
    If encryption is disabled (no ENCRYPTION_KEY), returns plaintext unchanged.
    Encrypted values are prefixed with "enc:" so we can detect them on read.
    """
    if not plaintext:
        return plaintext
    
    cipher = _get_fernet()
    if cipher is None:
        # Encryption disabled - store plaintext
        return plaintext
    
    try:
        encrypted = cipher.encrypt(plaintext.encode())
        # Base64-encode the encrypted bytes and prefix with "enc:"
        return f"enc:{encrypted.decode()}"
    except Exception as exc:
        logger.exception("Encryption failed: %s", exc)
        # Fall back to plaintext on error (log the issue but don't crash)
        return plaintext


def decrypt_field(ciphertext: str) -> str:
    """
    Decrypt a string field from database.
    
    If the value doesn't start with "enc:", assume it's plaintext (for backward compatibility).
    """
    if not ciphertext:
        return ciphertext
    
    # Not encrypted - return as-is
    if not ciphertext.startswith("enc:"):
        return ciphertext
    
    cipher = _get_fernet()
    if cipher is None:
        logger.warning("Encrypted data found but ENCRYPTION_KEY not set - returning [ENCRYPTED]")
        return "[ENCRYPTED - KEY MISSING]"
    
    try:
        # Strip "enc:" prefix and decrypt
        encrypted_b64 = ciphertext[4:]
        decrypted = cipher.decrypt(encrypted_b64.encode())
        return decrypted.decode()
    except InvalidToken:
        logger.error("Decryption failed - invalid token or wrong key")
        return "[ENCRYPTED - INVALID KEY]"
    except Exception as exc:
        logger.exception("Decryption failed: %s", exc)
        return "[ENCRYPTED - DECRYPTION ERROR]"


def is_encryption_enabled() -> bool:
    """Check if field encryption is enabled."""
    return _get_fernet() is not None


def should_encrypt_for_business(business_id: str) -> bool:
    """
    Check if encryption should be applied for a given business.
    
    Currently: always encrypt if ENCRYPTION_KEY is set (recommended).
    Could be per-business in the future (e.g., only Techne).
    """
    # For now, if encryption is enabled, use it for all businesses
    # (NM2TECH doesn't handle PHI but encryption doesn't hurt)
    return is_encryption_enabled()


def generate_key() -> str:
    """
    Generate a new Fernet encryption key.
    
    Store this in ENCRYPTION_KEY environment variable.
    
    Example:
        python -c "from app.encryption import generate_key; print(generate_key())"
    """
    return Fernet.generate_key().decode()
