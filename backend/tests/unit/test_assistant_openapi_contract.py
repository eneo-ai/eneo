"""The assistant update contract says what null does to each field."""

import pytest

from eneo.server.main import get_application


@pytest.fixture(scope="module")
def description() -> str:
    spec = get_application().openapi()
    return spec["paths"]["/api/v1/assistants/{id}/"]["post"]["description"]


def test_null_and_omission_keep_a_list_and_an_empty_list_clears_it(
    description: str,
) -> None:
    assert "Omitting a field leaves it unchanged" in description
    assert "An empty list clears a list field" in description
    for field in (
        "groups",
        "websites",
        "attachments",
        "integration_knowledge_list",
        "mcp_servers",
        "mcp_tools",
        "enabled_capabilities",
        "skill_bindings",
    ):
        assert field in description


def test_the_fields_null_changes_are_named(description: str) -> None:
    # Null clears these four nullable values ...
    assert (
        "Null clears description, metadata_json, icon_id and data_retention_days"
        in description
    )
    # ... and resets the model settings to their defaults, as on develop.
    assert "Null completion_model_kwargs resets the model settings" in description
