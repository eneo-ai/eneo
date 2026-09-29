"""Execute usage aggregation SQL against a small in-memory database."""

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.users_table import Users
from eneo.token_usage.infrastructure.user_token_usage_analyzer import (
    UserTokenUsageAnalyzer,
)

TENANT = UUID(int=1)
START = datetime(2026, 9, 1)
END = datetime(2026, 10, 1)


@pytest.fixture
def analyzer():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    # Only the columns read by this aggregate are needed; no application server,
    # external database or ORM relationship fixtures are involved.
    tables = {}
    for model, names in [
        (Users, ["id", "username", "email", "tenant_id"]),
        (Sessions, ["id", "user_id"]),
        (
            Questions,
            [
                "id",
                "session_id",
                "tenant_id",
                "created_at",
                "num_tokens_question",
                "num_tokens_answer",
            ],
        ),
        (
            AppRuns,
            [
                "id",
                "user_id",
                "tenant_id",
                "created_at",
                "num_tokens_input",
                "num_tokens_output",
            ],
        ),
        (HelpAssistantRuns, ["id", "session_id"]),
    ]:
        columns = []
        for name in names:
            source = model.__table__.c[name]
            column_type = (
                sa.Uuid(native_uuid=False)
                if isinstance(source.type, sa.Uuid)
                else source.type
            )
            columns.append(sa.Column(name, column_type))
        tables[model] = sa.Table(model.__tablename__, metadata, *columns)
    metadata.create_all(engine)
    with engine.begin() as connection:
        for index in range(31):
            user_id = UUID(int=100 + index)
            session_id = UUID(int=1000 + index)
            connection.execute(
                tables[Users]
                .insert()
                .values(
                    id=user_id,
                    tenant_id=TENANT,
                    username="needle_account" if index == 0 else f"person-{index:02d}",
                    email=f"person-{index}@example.com",
                )
            )
            connection.execute(
                tables[Sessions].insert().values(id=session_id, user_id=user_id)
            )
            connection.execute(
                tables[Questions]
                .insert()
                .values(
                    id=UUID(int=2000 + index),
                    session_id=session_id,
                    tenant_id=TENANT,
                    created_at=START,
                    num_tokens_question=1 if index == 0 else 100 + index,
                    num_tokens_answer=0,
                )
            )
        for user_id, username, email, tenant_id in [
            (UUID(int=200), None, "needle_app@example.com", TENANT),
            (UUID(int=201), "needlexaccount", "unrelated@example.com", TENANT),
            (UUID(int=300), "needle_foreign", "foreign@example.com", UUID(int=2)),
        ]:
            connection.execute(
                tables[Users]
                .insert()
                .values(id=user_id, username=username, email=email, tenant_id=tenant_id)
            )
            connection.execute(
                tables[AppRuns]
                .insert()
                .values(
                    id=UUID(int=user_id.int + 5000),
                    user_id=user_id,
                    tenant_id=tenant_id,
                    created_at=START,
                    num_tokens_input=3,
                    num_tokens_output=0,
                )
            )
        connection.execute(
            tables[AppRuns]
            .insert()
            .values(
                id=UUID(int=9999),
                user_id=UUID(int=100),
                tenant_id=TENANT,
                created_at=START,
                num_tokens_input=2,
                num_tokens_output=0,
            )
        )
        session = AsyncMock(spec=AsyncSession)
        session.execute.side_effect = connection.execute
        yield UserTokenUsageAnalyzer(session)
    engine.dispose()


async def test_search_finds_users_outside_the_first_page(analyzer):
    first = await analyzer.get_user_token_usage(TENANT, START, END, per_page=25)
    assert len(first.users) == 25
    assert all(
        user.user_id not in {UUID(int=100), UUID(int=200)} for user in first.users
    )
    result = await analyzer.get_user_token_usage(
        TENANT, START, END, per_page=25, search="NEEDLE_"
    )
    assert {user.user_id for user in result.users} == {UUID(int=100), UUID(int=200)}
    assert result.total_users == 2


async def test_count_and_stable_pagination_use_the_same_filter(analyzer):
    pages = [
        await analyzer.get_user_token_usage(
            TENANT, START, END, page=page, per_page=1, search="needle_"
        )
        for page in (1, 2)
    ]
    assert [page.total_users for page in pages] == [2, 2]
    assert [page.users[0].user_id for page in pages] == [UUID(int=200), UUID(int=100)]
    ascending = await analyzer.get_user_token_usage(
        TENANT, START, END, per_page=1, search="needle_", sort_order="asc"
    )
    assert ascending.users[0].user_id == UUID(int=100)


async def test_search_combines_chat_and_app_usage_for_the_same_user(analyzer):
    result = await analyzer.get_user_token_usage(
        TENANT, START, END, search=" needle_account "
    )
    assert result.total_users == 1
    assert result.users[0].total_input_tokens == 3
    assert result.users[0].total_requests == 2


async def test_email_search_supports_users_without_a_username(analyzer):
    result = await analyzer.get_user_token_usage(
        TENANT, START, END, search="NEEDLE_APP@EXAMPLE.COM"
    )
    assert result.total_users == 1
    assert result.users[0].username == "needle_app@example.com"


async def test_no_matches_returns_an_empty_result_and_zero_count(analyzer):
    result = await analyzer.get_user_token_usage(TENANT, START, END, search="absent")
    assert result.users == []
    assert result.total_users == 0
