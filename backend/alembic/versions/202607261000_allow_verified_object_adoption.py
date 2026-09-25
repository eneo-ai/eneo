"""allow verified object content to publish atomically

Revision ID: 202607261000
Revises: 202607251700
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607261000"
down_revision: str | None = "202607251700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_initial_owner_fence(*, verified_object_adoption: bool) -> None:
    object_store_initial_states = (
        "'pending', 'available'" if verified_object_adoption else "'pending'"
    )
    allowed_initial_state = (
        "(NEW.storage_kind = 'postgres_inline' AND NEW.state = 'available') "
        "OR (NEW.storage_kind = 'object_store' AND "
        f"NEW.state IN ({object_store_initial_states}))"
    )
    # The AVAILABLE/current-transaction predicate relies on the owner trigger
    # remaining DEFERRABLE INITIALLY DEFERRED so the first reference exists at
    # commit.
    initial_owner_required = (
        "content.state = 'pending' OR (content.state = 'available' "
        "AND content.creation_transaction_id = txid_current())"
        if verified_object_adoption
        else "content.state = 'pending' OR (content.storage_kind = 'postgres_inline' "
        "AND content.state = 'available')"
    )
    op.execute(f"""
        CREATE OR REPLACE FUNCTION object_content_pending_owner_fence()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT ({allowed_initial_state}) THEN
                RAISE EXCEPTION
                    'object content has an invalid initial storage state'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM object_contents content
                WHERE content.id = NEW.id
                  AND ({initial_owner_required})
                  AND NOT EXISTS (
                      SELECT 1 FROM file_content_references
                      WHERE content_id = content.id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM info_blob_content_references
                      WHERE content_id = content.id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM icon_content_references
                      WHERE content_id = content.id
                  )
            ) THEN
                RAISE EXCEPTION
                    'new object content requires an initial owner'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)


def _replace_reference_insert_fence(*, verified_object_adoption: bool) -> None:
    initial_reference = (
        "content.state = 'pending' OR (content.state = 'available' "
        "AND content.creation_transaction_id = txid_current())"
        if verified_object_adoption
        else "content.state = 'pending' OR (content.storage_kind = 'postgres_inline' "
        "AND content.state = 'available' "
        "AND content.creation_transaction_id = txid_current())"
    )
    op.execute(f"""
        CREATE OR REPLACE FUNCTION object_content_reference_insert_fence()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            content object_contents%ROWTYPE;
            expected_access_class text;
            owner_missing boolean;
            reference_delta integer;
            target_content_id uuid;
            tenant_mismatch boolean;
        BEGIN
            expected_access_class := CASE
                WHEN TG_TABLE_NAME = 'icon_content_references'
                    THEN 'public_immutable'
                ELSE 'private_resource'
            END;

            FOR target_content_id IN
                SELECT DISTINCT content_id
                FROM new_references
                ORDER BY content_id
            LOOP
                SELECT * INTO content
                FROM object_contents
                WHERE id = target_content_id
                FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'referenced object content does not exist';
                END IF;

                IF TG_TABLE_NAME = 'file_content_references' THEN
                    SELECT
                        count(*)::integer,
                        bool_or(owner.id IS NULL),
                        bool_or(owner.tenant_id IS DISTINCT FROM content.tenant_id)
                    INTO reference_delta, owner_missing, tenant_mismatch
                    FROM new_references AS reference
                    LEFT JOIN files AS owner ON owner.id = reference.file_id
                    WHERE reference.content_id = target_content_id;
                ELSIF TG_TABLE_NAME = 'info_blob_content_references' THEN
                    SELECT
                        count(*)::integer,
                        bool_or(owner.id IS NULL),
                        bool_or(owner.tenant_id IS DISTINCT FROM content.tenant_id)
                    INTO reference_delta, owner_missing, tenant_mismatch
                    FROM new_references AS reference
                    LEFT JOIN info_blobs AS owner
                        ON owner.id = reference.info_blob_id
                    WHERE reference.content_id = target_content_id;
                ELSE
                    SELECT
                        count(*)::integer,
                        bool_or(owner.id IS NULL),
                        bool_or(owner.tenant_id IS DISTINCT FROM content.tenant_id)
                    INTO reference_delta, owner_missing, tenant_mismatch
                    FROM new_references AS reference
                    LEFT JOIN icons AS owner ON owner.id = reference.icon_id
                    WHERE reference.content_id = target_content_id;
                END IF;

                IF owner_missing THEN
                    RAISE EXCEPTION
                        'object content reference owner does not exist';
                END IF;
                IF tenant_mismatch THEN
                    RAISE EXCEPTION 'object content reference tenant mismatch';
                END IF;
                IF content.access_class <> expected_access_class THEN
                    RAISE EXCEPTION 'object content access class mismatch';
                END IF;
                IF content.delete_requested_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'object content with delete intent cannot be attached';
                END IF;
                IF {initial_reference} THEN
                    IF content.reference_count <> 0
                        OR reference_delta <> 1
                        OR content.creation_transaction_id <> txid_current()
                    THEN
                        RAISE EXCEPTION
                            'new object content may only receive one first '
                            'reference in its creation transaction';
                    END IF;
                ELSIF content.state <> 'available' THEN
                    RAISE EXCEPTION
                        'only available object content can receive a later reference';
                END IF;

                UPDATE object_contents
                SET reference_count = reference_count + reference_delta,
                    reference_audited_at = NULL,
                    updated_at = now()
                WHERE id = content.id;
            END LOOP;
            RETURN NULL;
        END;
        $$
    """)


def upgrade() -> None:
    _replace_initial_owner_fence(verified_object_adoption=True)
    _replace_reference_insert_fence(verified_object_adoption=True)


def downgrade() -> None:
    _replace_initial_owner_fence(verified_object_adoption=False)
    _replace_reference_insert_fence(verified_object_adoption=False)
