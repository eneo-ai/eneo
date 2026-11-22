"""remove file and conversation names from stored audit rows

An audit row says who did what, when and to which object, never text that
retention removes. Rows stored before this version copied such text:

- a file row named the file in its description and target;
- an upload to a collection named the file in its target;
- a tool view's call, a document export and a saved document version named
  their conversation (its first question or a title made from its turns);
- an assistant update named the files attached or detached.

Each file row now gets the fixed description its writer uses, its target is
named "file" and a filename key goes; an upload to a collection gets its
fixed description and loses the filename. A conversation target is named
"conversation", and attachment changes keep each file's id, scope and mode.
Who, what, when and every id stay. Rows of other actions, and collection
uploads counted without a file name, are left as they are.

The rows are rewritten in batches, each its own short transaction, in id
order; the upgrade can be run again. The texts repeat those in
`eneo.audit.domain.removable_names`, so this revision imports nothing from
the application. Downgrade restores nothing: the names are gone.

Revision ID: 202611091000
Revises: 202611090600
Create Date: 2026-11-09 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611091000"
down_revision: str | None = "202611090600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FILE_ACTIONS = (
    "'file_uploaded', 'file_deleted', 'file_original_download_link_created', "
    "'file_original_downloaded', 'file_signed_url_minted'"
)
_CONVERSATION_ACTIONS = (
    "'mcp_app_tool_called', 'document_exported', 'document_version_saved'"
)
_ATTACHMENTS = "'{changes,knowledge_sources,attachments}'"

_BATCH_ROWS = 5000
_REMOVE_NAMES = f"""
WITH batch AS (
    SELECT id FROM audit_logs
    WHERE id > CAST(:after AS uuid)
      AND action IN ({_FILE_ACTIONS}, {_CONVERSATION_ACTIONS}, 'assistant_updated')
    ORDER BY id
    LIMIT {_BATCH_ROWS}
), files AS (
    UPDATE audit_logs
    SET description = CASE action
            WHEN 'file_uploaded' THEN 'Uploaded a file'
            WHEN 'file_deleted' THEN 'Deleted a file'
            WHEN 'file_original_download_link_created'
                THEN 'Created an original download link for a file'
            WHEN 'file_original_downloaded'
                THEN 'Original file accessed with a signed link'
            WHEN 'file_signed_url_minted' THEN 'Minted a signed URL for a file'
            ELSE description
        END,
        metadata = CASE
            WHEN jsonb_typeof(metadata -> 'target') = 'object'
                THEN jsonb_set(
                    metadata #- '{{target,filename}}', '{{target,name}}', '"file"'
                )
            ELSE metadata
        END #- '{{extra,filename}}'
    WHERE id IN (SELECT id FROM batch)
      AND action IN ({_FILE_ACTIONS})
      AND NOT coalesce(metadata -> 'target' ? 'group_id', false)
), collections AS (
    UPDATE audit_logs
    SET description = 'Uploaded a file to collection/group',
        metadata = metadata #- '{{target,filename}}'
    WHERE id IN (SELECT id FROM batch)
      AND action IN ({_FILE_ACTIONS})
      AND metadata -> 'target' ? 'group_id'
      AND metadata -> 'target' ? 'filename'
), conversations AS (
    UPDATE audit_logs
    SET metadata = jsonb_set(metadata, '{{target,name}}', '"conversation"')
    WHERE id IN (SELECT id FROM batch)
      AND action IN ({_CONVERSATION_ACTIONS})
      AND jsonb_typeof(metadata -> 'target') = 'object'
), attachments AS (
    UPDATE audit_logs
    SET metadata = jsonb_set(metadata, {_ATTACHMENTS}, coalesce((
        SELECT jsonb_object_agg(key, CASE
            WHEN jsonb_typeof(value) = 'array' THEN (
                SELECT coalesce(jsonb_agg(CASE
                    WHEN jsonb_typeof(item) = 'object' THEN item - 'name'
                    ELSE item
                END ORDER BY position), '[]'::jsonb)
                FROM jsonb_array_elements(value) WITH ORDINALITY AS listed(item, position)
            )
            ELSE value
        END)
        FROM jsonb_each(metadata #> {_ATTACHMENTS})
    ), '{{}}'::jsonb))
    WHERE id IN (SELECT id FROM batch)
      AND action = 'assistant_updated'
      AND jsonb_typeof(metadata #> {_ATTACHMENTS}) = 'object'
)
SELECT id::text FROM batch ORDER BY id DESC LIMIT 1
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        after = "00000000-0000-0000-0000-000000000000"
        while (
            last := bind.execute(sa.text(_REMOVE_NAMES), {"after": after}).scalar()
        ) is not None:
            after = last


def downgrade() -> None:
    # The names are gone; nothing restores them.
    pass
