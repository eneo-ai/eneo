"""CLI tool to generate Fernet encryption keys for tenant credentials.

Usage:
    cd backend
    uv run python -m intric.cli.generate_encryption_key
"""

from cryptography.fernet import Fernet


def main():
    key = Fernet.generate_key().decode()

    print("=" * 60)
    print("Generated Fernet Encryption Key")
    print("=" * 60)
    print()
    print("Add this to your .env file:")
    print()
    print(f"ENCRYPTION_KEY={key}")
    print()
    print("IMPORTANT:")
    print("- Keep this key secure (never commit to git)")
    print("- Backup this key (cannot decrypt without it)")
    print("- Losing this key = losing all encrypted credentials")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
