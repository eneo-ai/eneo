from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.token_usage.infrastructure.provider_token_usage_repo import (
    ProviderTokenUsageRepository,
    ProviderTokenUsageTenantMismatchError,
)


def _record_args() -> dict[str, object]:
    return {
        "tenant_id": uuid4(),
        "principal_user_id": uuid4(),
        "principal_service_id": None,
        "completion_model_id": uuid4(),
        "source_type": "flow_provider_call",
        "source_id": uuid4(),
        "input_tokens": 13,
        "output_tokens": 5,
        "occurred_at": datetime.now(timezone.utc),
    }


@pytest.mark.parametrize(
    ("model_is_in_tenant", "principal_is_in_tenant"),
    [(False, True), (True, False), (False, False)],
)
async def test_provider_usage_requires_model_and_principal_in_same_tenant(
    model_is_in_tenant: bool,
    principal_is_in_tenant: bool,
) -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[model_is_in_tenant, principal_is_in_tenant])
    repository = ProviderTokenUsageRepository(session)

    with pytest.raises(ProviderTokenUsageTenantMismatchError) as exc_info:
        await repository.record(**_record_args())  # type: ignore[arg-type]

    assert str(exc_info.value) == (
        "Provider usage model and principal must belong to its tenant."
    )
    session.execute.assert_not_awaited()


async def test_provider_usage_is_written_idempotently_after_tenant_checks() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[True, True])
    repository = ProviderTokenUsageRepository(session)
    values = _record_args()

    await repository.record(**values)  # type: ignore[arg-type]

    assert session.scalar.await_count == 2
    model_query = session.scalar.await_args_list[0].args[0]
    model_sql = str(model_query)
    assert "completion_models.id = " in model_sql
    assert "completion_models.tenant_id = " in model_sql
    assert True in model_query.compile().params.values()
    assert values["completion_model_id"] in model_query.compile().params.values()
    assert values["tenant_id"] in model_query.compile().params.values()

    principal_query = session.scalar.await_args_list[1].args[0]
    principal_sql = str(principal_query)
    assert "users.id = " in principal_sql
    assert "users.tenant_id = " in principal_sql
    assert True in principal_query.compile().params.values()
    assert values["principal_user_id"] in principal_query.compile().params.values()
    assert values["tenant_id"] in principal_query.compile().params.values()

    statement = session.execute.await_args.args[0]
    compiled_statement = statement.compile()
    assert compiled_statement.params["tenant_id"] == values["tenant_id"]
    assert compiled_statement.params["principal_user_id"] == values["principal_user_id"]
    assert compiled_statement.params["principal_service_id"] is None
    assert (
        compiled_statement.params["completion_model_id"]
        == values["completion_model_id"]
    )
    assert compiled_statement.params["source_type"] == values["source_type"]
    assert compiled_statement.params["source_id"] == values["source_id"]
    assert compiled_statement.params["input_tokens"] == values["input_tokens"]
    assert compiled_statement.params["output_tokens"] == values["output_tokens"]
    assert compiled_statement.params["occurred_at"] == values["occurred_at"]
    assert (
        statement._post_values_clause.constraint_target  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]
        == "uq_provider_token_usages_source"
    )


async def test_provider_usage_checks_service_principal_tenant() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[True, True])
    repository = ProviderTokenUsageRepository(session)
    values = _record_args()
    values["principal_user_id"] = None
    values["principal_service_id"] = uuid4()

    await repository.record(**values)  # type: ignore[arg-type]

    principal_query = session.scalar.await_args_list[1].args[0]
    principal_sql = str(principal_query)
    assert "service_principals.id = " in principal_sql
    assert "service_principals.tenant_id = " in principal_sql
    assert values["principal_service_id"] in principal_query.compile().params.values()
    assert values["tenant_id"] in principal_query.compile().params.values()
    statement = session.execute.await_args.args[0]
    assert (
        statement.compile().params["principal_service_id"]
        == values["principal_service_id"]
    )


@pytest.mark.parametrize(
    ("user_id", "service_id"),
    [(None, None), (uuid4(), uuid4())],
)
async def test_provider_usage_requires_exactly_one_principal(
    user_id: object,
    service_id: object,
) -> None:
    repository = ProviderTokenUsageRepository(AsyncMock())
    values = _record_args()
    values["principal_user_id"] = user_id
    values["principal_service_id"] = service_id

    with pytest.raises(ValueError) as exc_info:
        await repository.record(**values)  # type: ignore[arg-type]

    assert str(exc_info.value) == (
        "Provider usage requires exactly one principal identity."
    )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("input_tokens", "Provider input token usage cannot be negative"),
        ("output_tokens", "Provider output token usage cannot be negative"),
    ],
)
async def test_provider_usage_rejects_negative_token_counts(
    field: str,
    message: str,
) -> None:
    repository = ProviderTokenUsageRepository(AsyncMock())
    values = _record_args()
    values[field] = -1

    with pytest.raises(ValueError) as exc_info:
        await repository.record(**values)  # type: ignore[arg-type]

    assert str(exc_info.value) == f"{message}."


async def test_provider_usage_accepts_zero_token_counts() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=[True, True])
    repository = ProviderTokenUsageRepository(session)
    values = _record_args()
    values["input_tokens"] = 0
    values["output_tokens"] = 0

    await repository.record(**values)  # type: ignore[arg-type]

    session.execute.assert_awaited_once()
