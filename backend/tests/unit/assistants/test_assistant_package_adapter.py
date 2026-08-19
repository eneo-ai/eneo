from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.assistants.assistant_package_adapter import (
    AssistantPackageAdapter,
    AssistantPackageBindingError,
    AssistantPackageImportBindings,
    AssistantPackageKnowledgeKind,
)
from eneo.resource_packages.manifest import EneoPackageKind


def _assistant() -> object:
    return SimpleNamespace(
        name="Kommunassistent",
        description="Svarar med kommunal kunskap",
        prompt=SimpleNamespace(text="Använd endast verifierade källor."),
        completion_model=SimpleNamespace(
            name="gpt-5-mini",
            provider_type="openai",
            litellm_model_name="openai/gpt-5-mini",
        ),
        collections=[
            SimpleNamespace(id=uuid4(), name="Policy"),
            SimpleNamespace(id=uuid4(), name="Avtal"),
        ],
        websites=[SimpleNamespace(id=uuid4(), name="Intranät")],
        integration_knowledge_list=[SimpleNamespace(id=uuid4(), name="SharePoint")],
    )


def test_real_assistant_adapter_exports_portable_prompt_model_and_knowledge() -> None:
    adapter = AssistantPackageAdapter()
    assistant = _assistant()

    payload = adapter.export_payload(assistant)  # type: ignore[arg-type]
    manifest = adapter.manifest_metadata(
        package_id="se.eneo.kommunassistent",
        package_version="1.0.0",
        assistant=assistant,  # type: ignore[arg-type]
    )

    assert manifest.kind is EneoPackageKind.ASSISTANT
    assert payload.prompt == "Använd endast verifierade källor."
    assert payload.model.name == "gpt-5-mini"
    assert [(item.kind, item.name) for item in payload.knowledge] == [
        (AssistantPackageKnowledgeKind.COLLECTION, "Avtal"),
        (AssistantPackageKnowledgeKind.COLLECTION, "Policy"),
        (AssistantPackageKnowledgeKind.INTEGRATION_KNOWLEDGE, "SharePoint"),
        (AssistantPackageKnowledgeKind.WEBSITE, "Intranät"),
    ]
    serialized = payload.model_dump_json()
    for resource in (
        assistant.collections
        + assistant.websites
        + assistant.integration_knowledge_list
    ):
        assert str(resource.id) not in serialized


def test_assistant_import_maps_portable_slots_to_target_instance_ids() -> None:
    adapter = AssistantPackageAdapter()
    payload = adapter.export_payload(_assistant())  # type: ignore[arg-type]
    target_model_id = uuid4()
    target_ids = {item.slot_ref: uuid4() for item in payload.knowledge}

    install = adapter.prepare_import(
        payload,
        AssistantPackageImportBindings(
            completion_model_id=target_model_id,
            knowledge_by_slot=target_ids,
        ),
    )

    assert install.completion_model_id == target_model_id
    assert install.collection_ids == (
        target_ids["collection:0001"],
        target_ids["collection:0002"],
    )
    assert install.integration_knowledge_ids == (
        target_ids["integration_knowledge:0001"],
    )
    assert install.website_ids == (target_ids["website:0001"],)


def test_assistant_import_rejects_missing_or_unexpected_target_bindings() -> None:
    adapter = AssistantPackageAdapter()
    payload = adapter.export_payload(_assistant())  # type: ignore[arg-type]
    required = {item.slot_ref: uuid4() for item in payload.knowledge}
    required.pop("collection:0001")
    required["collection:9999"] = uuid4()

    with pytest.raises(AssistantPackageBindingError) as exc_info:
        adapter.prepare_import(
            payload,
            AssistantPackageImportBindings(
                completion_model_id=uuid4(),
                knowledge_by_slot=required,
            ),
        )

    assert exc_info.value.missing == {"collection:0001"}
    assert exc_info.value.unexpected == {"collection:9999"}
