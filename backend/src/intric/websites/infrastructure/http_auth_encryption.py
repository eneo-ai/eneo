"""HTTP auth credentials encryption service.

Why Infrastructure Layer:
- Encryption is a technical concern, not business logic
- Uses external library (cryptography)
- Configuration-dependent (encryption key from environment)
- Domain layer stays pure and testable
"""

import base64
import os
from cryptography.fernet import Fernet

from intric.websites.domain.http_auth_credentials import HttpAuthCredentials


class HttpAuthEncryptionService:
    """Infrastructure service for encrypting/decrypting HTTP auth credentials.

    Security Design:
    - Uses Fernet (symmetric encryption - AES 128 CBC + HMAC)
    - Key stored in environment variable (WEBSITE_AUTH_ENCRYPTION_KEY)
    - Credentials encrypted at rest in database
    - Decryption only happens when needed for crawling
    """

    def __init__(self):
        self._fernet = self._initialize_fernet()

    def _initialize_fernet(self) -> Fernet:
        """Initialize Fernet cipher with encryption key from environment.

        Raises:
            RuntimeError: If encryption key not found or invalid
        """
        encryption_key = os.environ.get("WEBSITE_AUTH_ENCRYPTION_KEY")

        if not encryption_key:
            raise RuntimeError(
                "WEBSITE_AUTH_ENCRYPTION_KEY not set. "
                "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )

        try:
            return Fernet(encryption_key.encode())
        except Exception as e:
            raise RuntimeError(f"Invalid WEBSITE_AUTH_ENCRYPTION_KEY: {str(e)}")

    def encrypt_password(self, password: str) -> str:
        """Encrypt password for storage.

        Args:
            password: Plaintext password

        Returns:
            Base64-encoded encrypted password safe for database storage
        """
        encrypted_bytes = self._fernet.encrypt(password.encode('utf-8'))
        return base64.urlsafe_b64encode(encrypted_bytes).decode()

    def decrypt_password(self, encrypted_password: str) -> str:
        """Decrypt password from storage.

        Args:
            encrypted_password: Base64-encoded encrypted password from database

        Returns:
            Plaintext password

        Raises:
            ValueError: If decryption fails (corrupted data or wrong key)
        """
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_password.encode())
            decrypted_bytes = self._fernet.decrypt(encrypted_bytes)
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Failed to decrypt password: {str(e)}")

    def encrypt_credentials(
        self,
        credentials: HttpAuthCredentials
    ) -> tuple[str, str, str]:
        """Encrypt credentials for database storage.

        Args:
            credentials: HttpAuthCredentials value object with plaintext password

        Returns:
            Tuple of (username, encrypted_password, auth_domain)
        """
        return (
            credentials.username,
            self.encrypt_password(credentials.password),
            credentials.auth_domain
        )

    def decrypt_credentials(
        self,
        username: str,
        encrypted_password: str,
        auth_domain: str
    ) -> HttpAuthCredentials:
        """Decrypt credentials from database storage.

        Args:
            username: Plaintext username from database
            encrypted_password: Encrypted password from database
            auth_domain: Auth domain from database

        Returns:
            HttpAuthCredentials value object with plaintext password

        Raises:
            ValueError: If decryption fails
        """
        plaintext_password = self.decrypt_password(encrypted_password)
        return HttpAuthCredentials(
            username=username,
            password=plaintext_password,
            auth_domain=auth_domain
        )
