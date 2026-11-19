"""The source rule: a session's one principal names its source, and tenant
scope for conversation reads never needs ``users``."""

from uuid import uuid4

import pytest

from eneo.sessions.session_source import (
    has_source,
    session_in_tenant,
    session_source,
    source_of,
    target_in_tenant,
)


@pytest.mark.parametrize(
    "source, column",
    [("user", "user_id"), ("api_key", "api_key_id"), ("widget", "widget_id")],
)
def test_the_principal_column_names_the_source(source, column):
    principals = {"user_id": None, "api_key_id": None, "widget_id": None}

    assert source_of(**{**principals, column: uuid4()}) == source
    assert str(has_source(source).compile()) == f"sessions.{column} IS NOT NULL"


def test_sql_source_checks_the_principals_in_the_python_twins_order():
    sql = str(session_source().compile(compile_kwargs={"literal_binds": True}))

    assert sql.index("sessions.user_id IS NOT NULL") < sql.index(
        "sessions.api_key_id IS NOT NULL"
    )
    assert "THEN 'user'" in sql and "THEN 'api_key'" in sql
    assert "ELSE 'widget'" in sql


def test_every_source_when_none_is_asked_for():
    assert str(has_source(None).compile()) == "true"


def test_tenant_scope_goes_through_the_target_space_not_users():
    for clause in (
        target_in_tenant(assistant_id=uuid4(), group_chat_id=None, tenant_id=uuid4()),
        target_in_tenant(assistant_id=None, group_chat_id=uuid4(), tenant_id=uuid4()),
        session_in_tenant(uuid4()),
    ):
        sql = str(clause.compile())
        assert "spaces.tenant_id" in sql
        assert "users" not in sql

    with pytest.raises(ValueError):
        target_in_tenant(assistant_id=None, group_chat_id=None, tenant_id=uuid4())
