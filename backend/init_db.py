import subprocess
import uuid
from datetime import datetime, timezone
from typing import Optional

import bcrypt
import psycopg2
from psycopg2 import sql
from pydantic_settings import BaseSettings, SettingsConfigDict


# Configuration
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    postgres_user: str
    postgres_host: str
    postgres_password: str
    postgres_port: int
    postgres_db: str

    default_tenant_name: Optional[str] = None
    default_tenant_quota_limit: Optional[int] = None
    default_user_name: Optional[str] = None
    default_user_email: Optional[str] = None
    default_user_password: Optional[str] = None

    public_origin: Optional[str] = None


settings = Settings()


# Alembic command
def run_alembic_migrations():
    try:
        subprocess.run(["alembic", "upgrade", "head"], check=True)
        print("Alembic migrations ran successfully.")
    except FileNotFoundError:
        print(
            "Error: alembic not found on PATH. Ensure it's installed in /app/.venv and PATH includes /app/.venv/bin"
        )
        exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error running alembic migrations: {e}")
        exit(1)


# Password hashing
def create_salt_and_hashed_password(plaintext_password: str):
    pwd_bytes = plaintext_password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password=pwd_bytes, salt=salt)
    return salt.decode(), hashed_password.decode("utf-8")


# Add tenant and user
def add_tenant_user(
    conn, tenant_name, quota_limit, user_name, user_email, user_password
):
    try:
        cur = conn.cursor()

        # Check if tenant already exists
        check_tenant_query = sql.SQL("SELECT id FROM tenants WHERE name = %s")
        cur.execute(check_tenant_query, (tenant_name,))
        tenant = cur.fetchone()

        if tenant is None:
            add_tenant_query = sql.SQL(
                "INSERT INTO tenants (name, quota_limit, state) VALUES (%s, %s, %s) RETURNING id"
            )
            cur.execute(add_tenant_query, (tenant_name, quota_limit, "active"))
            tenant_id = cur.fetchone()[0]
        else:
            print(f"Tenant {tenant_name} already exists. Using existing tenant.")
            tenant_id = tenant[0]

        # Check if user already exists
        check_user_query = sql.SQL(
            "SELECT id FROM users WHERE email = %s AND tenant_id = %s"
        )
        cur.execute(check_user_query, (user_email, tenant_id))
        user = cur.fetchone()

        if user is None:
            salt, hashed_pass = create_salt_and_hashed_password(user_password)
            add_user_query = sql.SQL(
                "INSERT INTO users (username, email, password, salt, tenant_id, used_tokens, state) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
            )
            cur.execute(
                add_user_query,
                (user_name, user_email, hashed_pass, salt, tenant_id, 0, "active"),
            )
            user_id = cur.fetchone()[0]
        else:
            print(f"User {user_email} already exists. Using existing user.")
            user_id = user[0]

        # Check if "Owner" role already exists for this tenant
        check_role_query = sql.SQL(
            "SELECT id FROM roles WHERE name = %s AND tenant_id = %s"
        )
        cur.execute(check_role_query, ("Owner", tenant_id))
        role = cur.fetchone()

        if role is None:
            owner_permissions = [
                "admin",
                "personal_chat",
                "assistants",
                "group_chats",
                "apps",
                "services",
                "collections",
                "insights",
                "AI",
                "websites",
                "integrations",
                "shared_spaces",
                "api_keys",
            ]
            add_role_query = sql.SQL(
                "INSERT INTO roles (name, permissions, tenant_id, predefined_source) "
                "VALUES (%s, %s, %s, %s) RETURNING id"
            )
            cur.execute(
                add_role_query, ("Owner", owner_permissions, tenant_id, "Owner")
            )
            role_id = cur.fetchone()[0]
        else:
            role_id = role[0]

        # Check if user already has the "Owner" role
        check_user_role_query = sql.SQL(
            "SELECT 1 FROM users_roles WHERE user_id = %s AND role_id = %s"
        )
        cur.execute(check_user_role_query, (user_id, role_id))
        user_role = cur.fetchone()

        if user_role is None:
            # Assign the "Owner" role to the user
            assign_role_to_user_query = sql.SQL(
                "INSERT INTO users_roles (user_id, role_id) VALUES (%s, %s)"
            )
            cur.execute(assign_role_to_user_query, (user_id, role_id))

        # Create organization space for the tenant (if not already exists)
        check_org_space_query = sql.SQL(
            """SELECT id FROM spaces
            WHERE tenant_id = %s AND user_id IS NULL AND tenant_space_id IS NULL"""
        )
        cur.execute(check_org_space_query, (tenant_id,))
        org_space = cur.fetchone()

        if org_space is None:
            org_space_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            add_org_space_query = sql.SQL(
                """INSERT INTO spaces (id, name, description, tenant_id, user_id, tenant_space_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, NULL, NULL, %s, %s)"""
            )
            cur.execute(
                add_org_space_query,
                (
                    org_space_id,
                    "Organization space",
                    "Delad knowledge för hela tenant",
                    tenant_id,
                    now,
                    now,
                ),
            )

        conn.commit()
        cur.close()
        print("Great! Your Tenant and User are all set up.")
    except Exception as e:
        print(f"Error adding tenant and user: {e}")
        conn.rollback()


def _normalize_origin(raw_origin: Optional[str]) -> Optional[str]:
    """Return a normalized http(s) origin, or None. Mirrors the seed migration."""
    if not raw_origin:
        return None
    origin = raw_origin.strip().rstrip("/")
    if origin.startswith(("http://", "https://")):
        return origin
    return None


# Seed the configured PUBLIC_ORIGIN into allowed_origins so CORS works out of the
# box on fresh installs. Idempotent: safe to run on every container start. The
# unique constraint is (tenant_id, url), so ON CONFLICT must match it.
def seed_allowed_origin(conn, public_origin, default_tenant_name):
    origin = _normalize_origin(public_origin)
    if origin is None:
        print(
            "Note! PUBLIC_ORIGIN not set or invalid. Skipping allowed_origins seed. "
            "Frontend origins must be registered via the sysadmin allowed-origins API."
        )
        return

    try:
        cur = conn.cursor()

        tenant = None
        if default_tenant_name:
            cur.execute(
                sql.SQL("SELECT id, name FROM tenants WHERE name = %s"),
                (default_tenant_name,),
            )
            tenant = cur.fetchone()

        if tenant is None:
            cur.execute(
                sql.SQL("SELECT id, name FROM tenants ORDER BY name ASC LIMIT 1")
            )
            tenant = cur.fetchone()

        if tenant is None:
            print("No tenants found; skipping allowed_origins seed.")
            cur.close()
            return

        tenant_id, tenant_name = tenant

        cur.execute(
            sql.SQL(
                "INSERT INTO allowed_origins (url, tenant_id) VALUES (%s, %s) "
                "ON CONFLICT (tenant_id, url) DO NOTHING"
            ),
            (origin, tenant_id),
        )
        conn.commit()
        cur.close()
        print(f"Allowed origin '{origin}' is registered for tenant '{tenant_name}'.")
    except Exception as e:
        print(f"Error seeding allowed origin: {e}")
        conn.rollback()


# Main script
if __name__ == "__main__":
    # Run alembic migrations
    run_alembic_migrations()

    # Connect to the database
    conn = psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )

    if (
        settings.default_tenant_name is None
        or settings.default_tenant_quota_limit is None
        or settings.default_user_name is None
        or settings.default_user_email is None
        or settings.default_user_password is None
    ):
        print(
            "Note! One or more environment variables for default tenant and user are not set. Skipping creation of default tenant and user."
        )
    else:
        add_tenant_user(
            conn,
            settings.default_tenant_name,
            settings.default_tenant_quota_limit,
            settings.default_user_name,
            settings.default_user_email,
            settings.default_user_password,
        )

    # Register PUBLIC_ORIGIN for CORS (idempotent; runs even when the default
    # tenant/user block above is skipped, e.g. on upgrades of existing installs).
    seed_allowed_origin(conn, settings.public_origin, settings.default_tenant_name)

    # Close the connection
    conn.close()
