from uuid import UUID

from eneo.flows.assistant_execution_snapshot import assistant_execution_surface_hash


def assistant_snapshot(assistant_id: UUID | str) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "schema_version": 2,
        "assistant_id": str(assistant_id),
        "origin": "flow_managed",
        "instructions": "Pinned at publish time.",
        "completion_model": None,
        "completion_model_kwargs": {},
        "knowledge_refs": [],
        "attachments": [],
        "inline_file_text": False,
    }
    snapshot["execution_surface_hash"] = assistant_execution_surface_hash(snapshot)
    return snapshot
