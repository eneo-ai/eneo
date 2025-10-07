"""Symmetric encryption for tenant API credentials using Fernet (AES-128-CBC + HMAC).

Provides encryption at rest for sensitive credentials stored in database.
Uses versioned format (enc:fernet:v1:) for future-proofing.
"""

from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from intric.main.logging import get_logger

logger = get_logger(__name__)


class EncryptionService:
    """Encrypts/decrypts tenant API credentials using Fernet.

    Format: enc:fernet:v1:<base64-token>
    """

    VERSION_PREFIX = "enc:fernet:v1:"
    MAX_CREDENTIAL_LENGTH = 10240  # 10KB - reasonable limit for API keys

    def __init__(self, encryption_key: Optional[str] = None):
        """Initialize with optional encryption key.

        Args:
            encryption_key: Base64-encoded Fernet key (32 bytes)
        """
        self._fernet: Optional[Fernet] = None
        if encryption_key:
            try:
                self._fernet = Fernet(encryption_key.encode())
                logger.info("Encryption service initialized")
            except Exception as e:
                logger.error(f"Invalid encryption key: {e}")
                raise ValueError(f"ENCRYPTION_KEY must be valid Fernet key: {e}")

    def is_active(self) -> bool:
        """Check if encryption is enabled."""
        return self._fernet is not None

    def __repr__(self) -> str:
        """Safe representation for debugging (doesn't expose key material)."""
        return f"<EncryptionService active={self.is_active()}>"

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext and return versioned token.

        Args:
            plaintext: API key to encrypt

        Returns:
            Versioned encrypted string: enc:fernet:v1:<ciphertext>

        Raises:
            ValueError: If encryption not configured or plaintext too long
        """
        if not self._fernet:
            raise ValueError("Encryption not configured")

        if not plaintext:
            raise ValueError("Cannot encrypt empty string")

        if len(plaintext) > self.MAX_CREDENTIAL_LENGTH:
            raise ValueError(
                f"Credential too long ({len(plaintext)} bytes). "
                f"Maximum allowed: {self.MAX_CREDENTIAL_LENGTH} bytes"
            )

        encrypted_bytes = self._fernet.encrypt(plaintext.encode())
        ciphertext = encrypted_bytes.decode()
        return f"{self.VERSION_PREFIX}{ciphertext}"

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt versioned token or pass through plaintext.

        Args:
            ciphertext: Either versioned token or legacy plaintext

        Returns:
            Decrypted plaintext API key

        Raises:
            ValueError: If decryption fails or version unsupported
        """
        if not ciphertext:
            raise ValueError("Cannot decrypt empty string")

        # Detect encrypted format
        if not ciphertext.startswith("enc:"):
            # Legacy plaintext - pass through for migration compatibility
            logger.info("Decrypting legacy plaintext credential")
            return ciphertext

        # Parse versioned format: enc:fernet:v1:<token>
        parts = ciphertext.split(":", 3)
        if len(parts) != 4:
            raise ValueError(f"Invalid encrypted format: {ciphertext[:30]}...")

        scheme, algorithm, version, token = parts

        if algorithm != "fernet" or version != "v1":
            raise ValueError(
                f"Unsupported encryption: {algorithm}:{version}. "
                f"Only fernet:v1 is supported."
            )

        if not self._fernet:
            raise ValueError(
                "Cannot decrypt: encryption key not configured. "
                "Set ENCRYPTION_KEY environment variable."
            )

        try:
            decrypted_bytes = self._fernet.decrypt(token.encode())
            return decrypted_bytes.decode()
        except InvalidToken as e:
            logger.error(f"Decryption failed: {e}")
            raise ValueError("Decryption failed: invalid token or wrong encryption key")

    def is_encrypted(self, value: str) -> bool:
        """Check if value is encrypted with versioned format."""
        return value.startswith(self.VERSION_PREFIX) if value else False
