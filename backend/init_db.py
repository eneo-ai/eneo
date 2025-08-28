import logging
import subprocess

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

settings = Settings()

# Alembic command
def run_alembic_migrations():
    try:
        subprocess.run(["poetry", "run", "alembic", "upgrade", "head"], check=True)
        print("Alembic migrations ran successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error running alembic migrations: {e}")
        exit(1)

# Password hashing
def create_salt_and_hashed_password(plaintext_password: str):
    pwd_bytes = plaintext_password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password=pwd_bytes, salt=salt)
    return salt.decode(), hashed_password.decode('utf-8')

# Add tenant and user
def add_tenant_user(conn, tenant_name, quota_limit, user_name, user_email, user_password):
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
            tenant_id = tenant[0]

        # Check if user already exists
        check_user_query = sql.SQL("SELECT id FROM users WHERE email = %s AND tenant_id = %s")
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
            user_id = user[0]

        # Check if "Owner" role already exists
        check_role_query = sql.SQL("SELECT id FROM predefined_roles WHERE name = %s")
        cur.execute(check_role_query, ("Owner",))
        role = cur.fetchone()

        if role is None:
            owner_permissions = [
                "admin",
                "assistants",
                "services",
                "collections",
                "insights",
                "AI",
                "editor",
                "websites",
            ]
            add_role_query = sql.SQL(
                "INSERT INTO predefined_roles (name, permissions) VALUES (%s, %s) RETURNING id"
            )
            cur.execute(add_role_query, ("Owner", owner_permissions))
            predefined_role_id = cur.fetchone()[0]
        else:
            predefined_role_id = role[0]

        # Check if user already has the "Owner" role
        check_user_role_query = sql.SQL(
            "SELECT 1 FROM users_predefined_roles WHERE user_id = %s AND predefined_role_id = %s"
        )
        cur.execute(check_user_role_query, (user_id, predefined_role_id))
        user_role = cur.fetchone()

        if user_role is None:
            # Assign the "Owner" role to the user
            assign_role_to_user_query = sql.SQL(
                "INSERT INTO users_predefined_roles (user_id, predefined_role_id) VALUES (%s, %s)"
            )
            cur.execute(assign_role_to_user_query, (user_id, predefined_role_id))

        # Check if any completion model exists and assign it to the user
        check_completion_models_query = sql.SQL(
            "SELECT id FROM completion_models limit 1"
        )
        cur.execute(check_completion_models_query)
        completion_model = cur.fetchone()

        if completion_model is None:
            # Check if gpt-4o exists
            check_model_query = sql.SQL("SELECT id FROM completion_models WHERE name = %s")
            cur.execute(check_model_query, ("gpt-4o",))
            model = cur.fetchone()

            # Add completion model if none exist
            if model is None:
                add_model_query = sql.SQL(
                    """INSERT INTO completion_models 
                    (name, nickname, family, token_limit, stability, hosting, description, org, vision, reasoning) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"""
                )
                cur.execute(
                    add_model_query,
                    (
                        "gpt-4o",
                        "GPT-4o",
                        "openai",
                        128000,
                        "stable",
                        "usa",
                        "OpenAI's latest and greatest model, trained on both text and images.",
                        "OpenAI",
                        True,
                        False,
                    ),
                )
                model_id = cur.fetchone()[0]
            else:
                model_id = model[0]
        else:
            model_id = completion_model[0]

        # Enable the completion model for the tenant
        check_model_setting_query = sql.SQL(
            """SELECT 1 FROM completion_model_settings 
            WHERE completion_model_id = %s AND tenant_id = %s"""
        )
        cur.execute(check_model_setting_query, (model_id, tenant_id))
        model_setting = cur.fetchone()

        if model_setting is None:
            enable_model_query = sql.SQL(
                """INSERT INTO completion_model_settings 
                (completion_model_id, tenant_id, is_org_enabled, is_org_default) 
                VALUES (%s, %s, %s, %s)"""
            )
            cur.execute(enable_model_query, (model_id, tenant_id, True, True))

        conn.commit()
        cur.close()
        print("Great! Your Tenant and User are all set up.")
    except Exception as e:
        print(f"Error adding tenant and user: {e}")
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

    # Add tenant and user
    add_tenant_user(
        conn,
        "ExampleTenant",
        "10737418240",
        "ExampleUser",
        "user@example.com",
        "Password1!",
    )

    # Close the connection
    conn.close()