"""Allow quarantined inline corruption to retain its observed payload.

Revision ID: 202609211200
Revises: 202609211100
"""

from alembic import op

revision = "202609211200"
down_revision = "202609211100"
branch_labels = None
depends_on = None


def _replace_storage_owner_fence(*, allow_quarantine: bool) -> None:
    quarantine_exclusion = ""
    if allow_quarantine:
        quarantine_exclusion = """
                    AND NOT (
                        content.state IN ('failed', 'retained')
                        AND content.failure_code IS NOT DISTINCT FROM 'backend_corrupt'
                    )
                    AND content.state <> 'delete_pending'
        """
    op.execute(f"""
        CREATE OR REPLACE FUNCTION object_content_storage_owner_fence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            content object_contents%ROWTYPE;
            inline_count integer;
            object_store_count integer;
            payload_size bigint;
            target_content_id uuid;
        BEGIN
            IF TG_TABLE_NAME = 'object_contents' THEN
                target_content_id := NEW.id;
            ELSIF TG_OP = 'DELETE' THEN
                target_content_id := OLD.content_id;
            ELSE
                target_content_id := NEW.content_id;
            END IF;

            SELECT * INTO content
            FROM object_contents
            WHERE id = target_content_id;
            IF NOT FOUND THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;

            SELECT count(*)::integer, max(octet_length(payload))
            INTO inline_count, payload_size
            FROM inline_content_payloads
            WHERE content_id = target_content_id;

            SELECT count(*)::integer INTO object_store_count
            FROM object_store_objects
            WHERE content_id = target_content_id;

            IF content.storage_kind = 'postgres_inline' THEN
                IF content.state = 'tombstoned' THEN
                    IF inline_count <> 0 OR object_store_count <> 0 THEN
                        RAISE EXCEPTION
                            'inline tombstone must not retain a byte backend';
                    END IF;
                ELSIF inline_count <> 1 OR object_store_count <> 0 THEN
                    RAISE EXCEPTION
                        'object content requires exactly one matching byte backend';
                ELSIF payload_size IS DISTINCT FROM content.size_bytes
                    {quarantine_exclusion} THEN
                    RAISE EXCEPTION
                        'inline payload size does not match object content';
                END IF;
            ELSIF content.storage_kind = 'object_store' THEN
                IF inline_count <> 0 OR object_store_count <> 1 THEN
                    RAISE EXCEPTION
                        'object content requires exactly one matching byte backend';
                END IF;
            ELSE
                RAISE EXCEPTION 'object content has an unsupported storage kind';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
    """)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    _replace_storage_owner_fence(allow_quarantine=True)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    _replace_storage_owner_fence(allow_quarantine=False)
