from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
PROMPT_CONTRACT_PATH = REPO_ROOT / "docs/refactor/ai-builder-prompt-contract.md"
AI_BUILDER_SOURCE_ROOT = REPO_ROOT / "backend/src/intric/flows/ai_builder"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_prompt_contract_artifact_tracks_stable_prompt_anchors() -> None:
    """Use exact substring anchors; this is a drift guard, not a prompt snapshot."""

    artifact = _read(PROMPT_CONTRACT_PATH)
    anchors = {
        "base_planning_state_version": (
            AI_BUILDER_SOURCE_ROOT / "ai_builder_knowledge_pack_protocol.py"
        ),
        "outline_flow": AI_BUILDER_SOURCE_ROOT
        / "ai_builder_knowledge_pack_protocol.py",
        "edit_flow": AI_BUILDER_SOURCE_ROOT / "ai_builder_knowledge_pack_protocol.py",
        "ref=": AI_BUILDER_SOURCE_ROOT / "ai_builder_prompts.py",
        "architecture_commit: null": AI_BUILDER_SOURCE_ROOT / "ai_builder_repair.py",
        "single raw JSON object": AI_BUILDER_SOURCE_ROOT / "ai_builder_repair.py",
        "Do NOT wrap": AI_BUILDER_SOURCE_ROOT / "ai_builder_repair.py",
        "Generate ONLY a new flow_description": AI_BUILDER_SOURCE_ROOT
        / "ai_builder_edit_proposal.py",
        "Respond with ONLY the new description text": AI_BUILDER_SOURCE_ROOT
        / "ai_builder_edit_proposal.py",
    }

    for anchor, owner_path in anchors.items():
        assert anchor in artifact
        assert anchor in _read(owner_path)
