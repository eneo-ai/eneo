"""The completion-model write schemas say what the validation does.

A completion model needs both token limits, so no write request accepts null
for them: a create must state both, and an update either states a positive
value or omits the field to keep the stored one."""

import pytest

from eneo.server.main import get_application

LIMITS = ("max_input_tokens", "max_output_tokens")


@pytest.fixture(scope="module")
def schemas() -> dict:
    return get_application().openapi()["components"]["schemas"]


def _allows_null(prop: dict) -> bool:
    options = prop.get("anyOf", [prop])
    return prop.get("nullable") is True or any(
        option.get("type") == "null" for option in options
    )


@pytest.mark.parametrize(
    "schema", ["CompletionModelCreate", "TenantCompletionModelCreate"]
)
def test_create_requires_both_limits_and_never_null(schemas: dict, schema: str):
    create = schemas[schema]
    for limit in LIMITS:
        assert limit in create["required"]
        assert not _allows_null(create["properties"][limit]), (schema, limit)
        assert "not declared" not in create["properties"][limit].get("description", "")


@pytest.mark.parametrize(
    "schema", ["PartialCompletionModelUpdate", "TenantCompletionModelUpdate"]
)
def test_update_limits_are_optional_and_never_null(schemas: dict, schema: str):
    update = schemas[schema]
    for limit in LIMITS:
        prop = update["properties"][limit]
        assert limit not in update.get("required", [])
        assert not _allows_null(prop), (schema, limit)
        assert "Omit" in prop["description"] and "null" in prop["description"]
