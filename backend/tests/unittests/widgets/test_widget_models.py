from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.mcp_servers.domain.entities.mcp_server import MCP_TOOL_CATALOG_HARD_MAX_COUNT
from eneo.widgets.domain.widget import WidgetTexts
from eneo.widgets.presentation.widget_models import (
    WidgetExternalToolsAcknowledge,
    WidgetUpdate,
)


def test_update_keeps_validated_values_and_distinguishes_false_from_omitted():
    update = WidgetUpdate(
        revision=3, texts=WidgetTexts(title="Kontakt"), show_sources=False
    )
    assert update.changes() == {"texts": update.texts, "show_sources": False}
    assert "theme" not in update.changes()
    assert "revision" not in update.changes()


def test_an_update_schema_offers_no_null_the_api_refuses():
    """A field is kept by leaving it out; the schema, and the client types
    generated from it, must not offer the null the API refuses."""
    properties = WidgetUpdate.model_json_schema()["properties"]
    assert "revision" in WidgetUpdate.model_json_schema()["required"]
    with pytest.raises(ValidationError, match="revision"):
        WidgetUpdate.model_validate({"name": "no revision"})
    offered = sorted(
        field
        for field, schema in properties.items()
        if schema.get("type") == "null"
        or any(branch.get("type") == "null" for branch in schema.get("anyOf", []))
    )
    assert offered == []
    assert properties["name"]["minLength"] == 1
    assert properties["allowed_origins"]["maxItems"] == 20

    with pytest.raises(ValidationError, match="cannot be null"):
        WidgetUpdate.model_validate({"revision": 1, "language": None})
    assert WidgetUpdate(revision=1).model_dump(exclude_unset=True) == {"revision": 1}


def test_an_acknowledgement_holds_every_tool_a_server_can_list():
    def body(count: int) -> dict[str, object]:
        return {
            "servers": [
                {"id": str(uuid4()), "tool_ids": [str(uuid4()) for _ in range(count)]}
            ]
        }

    acknowledged = WidgetExternalToolsAcknowledge.model_validate(
        body(MCP_TOOL_CATALOG_HARD_MAX_COUNT)
    )
    assert len(acknowledged.servers[0].tool_ids) == MCP_TOOL_CATALOG_HARD_MAX_COUNT
    with pytest.raises(ValidationError, match="tool_ids"):
        WidgetExternalToolsAcknowledge.model_validate(
            body(MCP_TOOL_CATALOG_HARD_MAX_COUNT + 1)
        )
