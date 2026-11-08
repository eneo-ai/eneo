"""Model-attributed chat usage, including consultations owned by a question."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql.selectable import Subquery

from eneo.database.tables.questions_table import Questions


def question_usage_rows(
    tenant_id: UUID, start_date: datetime, end_date: datetime
) -> Subquery:
    """One row per parent or specialist completion; never bill children as the parent model."""
    scope = (
        Questions.tenant_id == tenant_id,
        Questions.created_at >= start_date,
        Questions.created_at <= end_date,
    )
    parents = sa.select(
        Questions.id,
        Questions.session_id,
        Questions.tenant_id,
        Questions.created_at,
        Questions.completion_model_id,
        Questions.num_tokens_question,
        Questions.num_tokens_answer,
    ).where(*scope)
    consultations = (
        sa.func.jsonb_array_elements(Questions.consultations)
        .table_valued(sa.column("value", JSONB))
        .lateral()
    )
    value = consultations.c.value
    children = (
        sa.select(
            sa.cast(value["id"].astext, PGUUID(as_uuid=True)).label("id"),
            Questions.session_id,
            Questions.tenant_id,
            Questions.created_at,
            sa.cast(value["completion_model_id"].astext, PGUUID(as_uuid=True)).label(
                "completion_model_id"
            ),
            sa.func.coalesce(
                sa.cast(value["input_tokens"].astext, sa.BigInteger), 0
            ).label("num_tokens_question"),
            sa.func.coalesce(
                sa.cast(value["output_tokens"].astext, sa.BigInteger), 0
            ).label("num_tokens_answer"),
        )
        .select_from(Questions)
        .join(consultations, sa.true())
        .where(*scope, value["completion_model_id"].astext.is_not(None))
    )
    return sa.union_all(parents, children).subquery("question_usage")
