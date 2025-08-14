"""Simple encryption utilities for storing sensitive data."""

import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from intric.main.config import get_settings


def _get_encryption_key() -> bytes:
    """Generate encryption key from URL signing key."""
    password = get_settings().url_signing_key.encode()
    salt = b'intric_website_auth'  # Static salt for consistency
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password))
    return key


def encrypt_password(password: str) -> str:
    """Encrypt a password for secure storage."""
    if not password:
        return ""
    
    key = _get_encryption_key()
    fernet = Fernet(key)
    encrypted = fernet.encrypt(password.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_password(encrypted_password: str) -> str:
    """Decrypt a stored password."""
    if not encrypted_password:
        return ""
    
    key = _get_encryption_key()
    fernet = Fernet(key)
    encrypted_bytes = base64.urlsafe_b64decode(encrypted_password)
    decrypted = fernet.decrypt(encrypted_bytes)
    return decrypted.decode()