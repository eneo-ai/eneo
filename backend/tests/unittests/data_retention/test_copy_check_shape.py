"""The copy check stays a probe per row on every read that carries it."""

import re

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from eneo.data_retention.derivations import copy_session_valid
from eneo.database.tables.sessions_table import Sessions


def test_each_existence_check_is_fenced():
    """Mutant: a check loses its OFFSET 0, so PostgreSQL may flatten it into a
    hash over every question on each conversation list (measured on 13 and 16)."""
    sql = str(
        sa.select(Sessions.id)
        .where(copy_session_valid(Sessions.id.expression))
        .compile(dialect=postgresql.dialect())
    )

    assert len(re.findall(r"EXISTS \(SELECT 1", sql)) == 2
    assert len(re.findall(r"OFFSET 0\)", sql)) == 2
