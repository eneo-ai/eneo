"""The OpenAPI owner restores the nulls FastAPI strips from declared examples."""

from eneo.server.main import _restore_stripped_example_nulls


def _spec() -> dict:
    return {
        "components": {
            "schemas": {
                "Edit": {
                    "type": "object",
                    "required": ["revision", "corrections_revision_id", "note"],
                    "properties": {
                        "revision": {"type": "integer"},
                        "corrections_revision_id": {
                            "anyOf": [
                                {"type": "string", "format": "uuid"},
                                {"type": "null"},
                            ]
                        },
                        "note": {"type": "string"},
                    },
                },
                "Page": {
                    "type": "object",
                    "required": ["items", "next_after_revision"],
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Edit"},
                        },
                        "next_after_revision": {
                            "anyOf": [{"type": "integer"}, {"type": "null"}]
                        },
                    },
                    # FastAPI already dropped every None from this example.
                    "example": {"items": [{"revision": 2, "note": "x"}]},
                },
            }
        },
        "paths": {
            "/pages/": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Page"},
                                    "example": {
                                        "items": [{"revision": 3, "note": "y"}]
                                    },
                                }
                            }
                        }
                    }
                }
            }
        },
    }


def test_required_nullable_keys_come_back_as_null_in_nested_examples() -> None:
    spec = _spec()

    _restore_stripped_example_nulls(spec)

    schema_example = spec["components"]["schemas"]["Page"]["example"]
    assert schema_example == {
        "items": [{"revision": 2, "note": "x", "corrections_revision_id": None}],
        "next_after_revision": None,
    }
    route_example = spec["paths"]["/pages/"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["example"]
    assert route_example == {
        "items": [{"revision": 3, "note": "y", "corrections_revision_id": None}],
        "next_after_revision": None,
    }


def test_missing_non_nullable_and_optional_keys_are_left_alone() -> None:
    spec = _spec()
    spec["components"]["schemas"]["Page"]["example"] = {"items": [{"revision": 2}]}

    _restore_stripped_example_nulls(spec)

    # `note` is required but not nullable: absent stays absent (a real
    # example defect the contract test must still catch).
    assert spec["components"]["schemas"]["Page"]["example"]["items"][0] == {
        "revision": 2,
        "corrections_revision_id": None,
    }
