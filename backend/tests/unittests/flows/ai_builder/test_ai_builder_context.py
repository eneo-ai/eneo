from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_context import (
    serialize_space_kbs,
    serialize_space_models,
)


def test_serialize_space_models_keeps_local_id_for_catalog_input() -> None:
    model_id = uuid4()
    space = SimpleNamespace(
        completion_models=[
            SimpleNamespace(id=model_id, name="gpt-5.4-nano", provider_type="openai")
        ]
    )

    assert serialize_space_models(space) == [
        {
            "id": str(model_id),
            "ref": str(model_id),
            "name": "gpt-5.4-nano",
            "display_name": "gpt-5.4-nano",
            "provider": "openai",
        }
    ]


def test_serialize_space_kbs_keeps_local_id_for_catalog_input() -> None:
    kb_id = uuid4()
    space = SimpleNamespace(
        collections=[
            SimpleNamespace(
                id=kb_id,
                name="Policy",
                description="Local policy reference material.",
            )
        ]
    )

    assert serialize_space_kbs(space) == [
        {
            "id": str(kb_id),
            "ref": str(kb_id),
            "name": "Policy",
            "display_name": "Policy",
            "description": "Local policy reference material.",
        }
    ]
