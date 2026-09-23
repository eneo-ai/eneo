import pytest
from pydantic import ValidationError

from eneo.widgets.presentation.widget_models import WidgetUpdate


def test_an_update_schema_offers_no_null_the_api_refuses():
    """A field is kept by leaving it out; the schema, and the client types
    generated from it, must not offer the null the API refuses."""
    properties = WidgetUpdate.model_json_schema()["properties"]
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
