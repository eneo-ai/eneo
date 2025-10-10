import base64
import hashlib
import hmac
import json
import time
from typing import Optional
from uuid import UUID

from intric.files.file_models import ContentDisposition
from intric.main.config import get_settings


def _get_signing_key():
    """Get the signing key from settings."""
    return get_settings().url_signing_key.encode()


SIGNING_KEY = _get_signing_key()


def generate_signed_token(
    file_id: UUID, expires_at: int, content_disposition: ContentDisposition
) -> str:
    """Generate a signed token for file access."""
    payload = {
        "file_id": str(file_id),
        "expires_at": expires_at,
        "content_disposition": content_disposition.value,
    }

    # Encode the payload as JSON and then base64
    message = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    # Create a signature using HMAC-SHA256
    signature = hmac.new(SIGNING_KEY, message.encode(), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode()

    # Return the token in the format message.signature
    return f"{message}.{signature_b64}"


def verify_signed_token(token: str) -> Optional[dict]:
    """Verify a signed token and return the payload if valid."""
    try:
        # Split the token into message and signature parts
        if "." not in token:
            return None

        message, signature_b64 = token.split(".")

        # Decode the signature
        try:
            signature = base64.urlsafe_b64decode(signature_b64)
        except Exception:
            return None

        # Compute the expected signature
        expected_signature = hmac.new(
            SIGNING_KEY, message.encode(), hashlib.sha256
        ).digest()

        # Compare signatures using constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(signature, expected_signature):
            return None

        # Decode the payload
        try:
            payload_json = base64.urlsafe_b64decode(message).decode()
            payload = json.loads(payload_json)
        except Exception:
            return None

        # Check if the URL has expired
        if payload["expires_at"] < int(time.time()):
            return None

        return payload
    except Exception:
        return None
