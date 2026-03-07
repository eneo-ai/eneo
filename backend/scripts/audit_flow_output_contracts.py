#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import text

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir / "src"))

from intric.database.database import sessionmanager
from intric.main.config import get_settings

PUBLISHED_AUDIT_SQL = text(
    """
    WITH published AS (
      SELECT f.id AS flow_id, f.tenant_id, f.published_version, fv.definition_json
      FROM flows f
      JOIN flow_versions fv
        ON fv.flow_id = f.id
       AND fv.version = f.published_version
       AND fv.tenant_id = f.tenant_id
      WHERE f.deleted_at IS NULL
        AND f.published_version IS NOT NULL
    ),
    steps AS (
      SELECT
        p.tenant_id,
        p.flow_id,
        p.published_version,
        s.ordinality::int AS step_pos,
        s.step
      FROM published p
      CROSS JOIN LATERAL jsonb_array_elements(
        CASE
          WHEN jsonb_typeof(p.definition_json->'steps') = 'array' THEN p.definition_json->'steps'
          ELSE '[]'::jsonb
        END
      ) WITH ORDINALITY AS s(step, ordinality)
    )
    SELECT
      tenant_id,
      flow_id,
      published_version,
      step_pos,
      step->>'output_type' AS output_type,
      step->'output_contract' AS output_contract,
      CASE
        WHEN coalesce(step->>'output_type','') = 'text'
         AND step ? 'output_contract'
         AND step->'output_contract' IS NOT NULL
         AND step->'output_contract' <> 'null'::jsonb
          THEN 'text_with_output_contract'
        WHEN coalesce(step->>'output_type','') IN ('pdf','docx')
         AND (
           step ? 'output_contract'
           AND step->'output_contract' IS NOT NULL
           AND step->'output_contract' <> 'null'::jsonb
           AND (
             jsonb_typeof(step->'output_contract') <> 'object'
             OR coalesce(step->'output_contract'->>'type','') NOT IN ('object','array')
           )
         )
          THEN 'pdf_docx_incompatible_output_contract'
      END AS violation_reason
    FROM steps
    WHERE
      (
        coalesce(step->>'output_type','') = 'text'
        AND step ? 'output_contract'
        AND step->'output_contract' IS NOT NULL
        AND step->'output_contract' <> 'null'::jsonb
      )
      OR
      (
        coalesce(step->>'output_type','') IN ('pdf','docx')
        AND (
          step ? 'output_contract'
          AND step->'output_contract' IS NOT NULL
          AND step->'output_contract' <> 'null'::jsonb
          AND (
            jsonb_typeof(step->'output_contract') <> 'object'
            OR coalesce(step->'output_contract'->>'type','') NOT IN ('object','array')
          )
        )
      )
    ORDER BY tenant_id, flow_id, step_pos
    """
)

LIVE_DRAFT_AUDIT_SQL = text(
    """
    SELECT
      fs.tenant_id,
      fs.flow_id,
      fs.step_order,
      fs.output_type,
      fs.output_contract,
      CASE
        WHEN fs.output_type = 'text'
          AND fs.output_contract IS NOT NULL
          AND fs.output_contract <> 'null'::jsonb
          THEN 'text_with_output_contract'
        WHEN fs.output_type IN ('pdf','docx')
          AND (
            fs.output_contract IS NOT NULL
            AND fs.output_contract <> 'null'::jsonb
            AND (
              jsonb_typeof(fs.output_contract) <> 'object'
              OR coalesce(fs.output_contract->>'type','') NOT IN ('object','array')
            )
          ) THEN 'pdf_docx_incompatible_output_contract'
      END AS violation_reason
    FROM flow_steps fs
    JOIN flows f ON f.id = fs.flow_id AND f.tenant_id = fs.tenant_id
    WHERE f.deleted_at IS NULL
      AND (
        (
          fs.output_type = 'text'
          AND fs.output_contract IS NOT NULL
          AND fs.output_contract <> 'null'::jsonb
        )
        OR
        (
          fs.output_type IN ('pdf','docx')
          AND (
            fs.output_contract IS NOT NULL
            AND fs.output_contract <> 'null'::jsonb
            AND (
              jsonb_typeof(fs.output_contract) <> 'object'
              OR coalesce(fs.output_contract->>'type','') NOT IN ('object','array')
            )
          )
        )
      )
    ORDER BY fs.tenant_id, fs.flow_id, fs.step_order
    """
)


def _print_rows(label: str, rows: list[dict[str, object]]) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("violation_reason", "unknown"))
        counts[reason] = counts.get(reason, 0) + 1
    print(f"\n[{label}] rows={len(rows)}")
    print(json.dumps({"counts": counts, "rows": rows}, default=str, indent=2))


async def main(include_drafts: bool) -> None:
    settings = get_settings()
    sessionmanager.init(settings.database_url)
    try:
        async with sessionmanager.connect() as conn:
            published_rows = [
                dict(row._mapping)
                for row in (await conn.execute(PUBLISHED_AUDIT_SQL)).fetchall()
            ]
            _print_rows("published", published_rows)

            if include_drafts:
                draft_rows = [
                    dict(row._mapping)
                    for row in (await conn.execute(LIVE_DRAFT_AUDIT_SQL)).fetchall()
                ]
                _print_rows("live_drafts", draft_rows)
    finally:
        await sessionmanager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Read-only audit for Flow output_contract compatibility."
    )
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Also scan live flow_steps rows for draft/in-progress flows.",
    )
    args = parser.parse_args()
    asyncio.run(main(include_drafts=args.include_drafts))
