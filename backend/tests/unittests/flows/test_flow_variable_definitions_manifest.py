from __future__ import annotations

import json
from pathlib import Path

from eneo.flows.flow_variable_definitions import flow_variable_definition_manifest


def test_frontend_flow_variable_manifest_matches_backend_owner() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    manifest_path = (
        repo_root
        / "frontend/apps/web/src/lib/features/flows/"
        / "flowVariableDefinitions.generated.json"
    )

    assert json.loads(manifest_path.read_text()) == flow_variable_definition_manifest()
