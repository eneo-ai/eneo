"""Reconstruction contract for requirements-state from conversation metadata.

Server dispatch persists the disclosure it emitted as
`metadata.requirements_summary` on the assistant message it writes inside the
commit_turn savepoint. `resolve_requirements_state` reads that shape back so
later turns can re-render the confirmed requirements into the system prompt
and gate plan creation on the user's confirmation of one exact version.
"""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    NamedContentFieldPayload,
    RequirementsDisclosureContent,
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    V23_DISCLOSURE_IDENTITY_FIELDS,
    build_requirements_version,
    render_confirmed_requirements_proposal_prompt_block,
    resolve_requirements_state,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME


def _disclosure(content: dict[str, object]) -> RequirementsSummaryPayload:
    """Stamp a disclosure with the version that hashes its content."""

    validated = RequirementsDisclosureContent.model_validate(content)
    return RequirementsSummaryPayload(
        **validated.model_dump(),
        requirements_version=build_requirements_version(validated),
    )


def _summary_payload() -> RequirementsSummaryPayload:
    return _disclosure(
        {
            "summary": "A flow that extracts data from PDFs into structured JSON.",
            "key_decisions": [
                {"topic": "Input", "decision": "Single PDF per run"},
                {"topic": "Output", "decision": "JSON with extracted fields"},
            ],
            "input_description": "A PDF document uploaded by the user.",
            "output_description": "JSON object with extracted key fields.",
            "assumptions": ["User provides legible PDFs"],
            "manual_setup_notes": ["Connect knowledge base with field glossary"],
        }
    )


class TestResolveRequirementsStateFromAssistantMetadata:
    def test_assistant_metadata_shape_populates_latest_summary(self) -> None:
        payload = _summary_payload()
        version = payload.requirements_version
        conversation = [
            ConversationMessage(role="user", content="Build a PDF extractor"),
            ConversationMessage(
                role="assistant",
                content="Here is the summary I have so far.",
                metadata={
                    "requirements_summary": payload.model_dump(mode="json"),
                    "requirements_version": version,
                },
            ),
        ]

        state = resolve_requirements_state(conversation)

        assert state.latest_summary is not None
        assert state.latest_summary.summary == payload.summary
        assert state.latest_version == version
        assert state.confirmed is False  # no user confirmation yet

    def test_user_confirmation_completes_the_confirmed_contract(self) -> None:
        payload = _summary_payload()
        version = payload.requirements_version
        conversation = [
            ConversationMessage(role="user", content="Build a PDF extractor"),
            ConversationMessage(
                role="assistant",
                content="Here is the summary I have so far.",
                metadata={
                    "requirements_summary": payload.model_dump(mode="json"),
                    "requirements_version": version,
                },
            ),
            ConversationMessage(
                role="user",
                content="",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": version,
                },
            ),
        ]

        state = resolve_requirements_state(conversation)

        assert state.latest_summary is not None
        assert state.latest_version == version
        assert state.confirmed_version == version
        assert state.confirmed is True
        assert state.confirmed_requirements_version == version

    def test_version_drift_on_user_confirmation_blocks_confirmed_flag(self) -> None:
        payload = _summary_payload()
        version = payload.requirements_version
        conversation = [
            ConversationMessage(
                role="assistant",
                content="Summary",
                metadata={
                    "requirements_summary": payload.model_dump(mode="json"),
                    "requirements_version": version,
                },
            ),
            ConversationMessage(
                role="user",
                content="",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": "57a1e" + "0" * 59,
                },
            ),
        ]

        state = resolve_requirements_state(conversation)

        assert state.latest_summary is not None
        assert state.confirmed is False

    def test_plan_tool_call_preserves_confirmation_for_revision_requests(self) -> None:
        payload = _summary_payload()
        version = payload.requirements_version
        conversation = [
            ConversationMessage(
                role="assistant",
                content="Summary",
                metadata={
                    "requirements_summary": payload.model_dump(mode="json"),
                    "requirements_version": version,
                },
            ),
            ConversationMessage(
                role="user",
                content="",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": version,
                },
            ),
            ConversationMessage(
                role="assistant",
                content="Here is the draft.",
                tool_calls=[
                    {
                        "id": "call_plan",
                        "name": PROPOSE_FLOW_TOOL_NAME,
                        "arguments": {"flow_name": "PDF extractor"},
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Draft saved.",
                tool_call_id="call_plan",
            ),
            ConversationMessage(role="user", content="Make the title shorter."),
        ]

        state = resolve_requirements_state(conversation)

        assert state.confirmed is True


class TestRenderConfirmedRequirementsBlocks:
    def test_confirmed_requirements_proposal_block_uses_user_relevant_fields_only(
        self,
    ) -> None:
        payload = _disclosure(
            {
                "summary": "Skapa ett mötesprotokoll.",
                "key_decisions": [
                    {"topic": "Indata", "decision": "Mötesljud vid körning."},
                ],
                "input_description": "Primär indata vid körning behöver granskas.",
                "output_description": "DOCX-protokoll.",
                "assumptions": [
                    "Planen ska följa kraven och underlaget i konversationen.",
                    "Inga extra fält.",
                ],
                "manual_setup_notes": ["Koppla transkriberingsmodellen."],
            }
        ).model_copy(
            update={
                "named_content_fields": [
                    NamedContentFieldPayload(
                        id="beslut",
                        label="beslut",
                        name="beslut",
                        segments=[],
                        unplaced=False,
                        can_contain_fields=False,
                    )
                ]
            }
        )

        prompt_block = render_confirmed_requirements_proposal_prompt_block(payload)

        assert prompt_block == "\n".join(
            (
                "- summary: Skapa ett mötesprotokoll.",
                "- output_description: DOCX-protokoll.",
                "- key_decisions:",
                "  - Indata: Mötesljud vid körning.",
                "- named_content_fields:",
                "  - beslut",
                "- assumptions:",
                "  - Inga extra fält.",
            )
        )
        assert "behöver granskas" not in prompt_block
        assert payload.requirements_version not in prompt_block

    def test_confirmed_requirements_proposal_block_returns_none_marker(
        self,
    ) -> None:
        assert render_confirmed_requirements_proposal_prompt_block(None) == "- none"

    def test_confirmed_requirements_proposal_block_returns_none_marker_for_boilerplate(
        self,
    ) -> None:
        payload = _disclosure(
            {
                "summary": (
                    "Jag har tillräckligt med information för att ta fram ett "
                    "förslag till flödesplan. Granska sammanfattningen innan "
                    "planen byggs."
                ),
                "key_decisions": [],
                "input_description": "Primär indata vid körning behöver granskas.",
                "output_description": "Huvudsakligt slutresultat behöver granskas.",
                "assumptions": [
                    "Planen ska följa kraven och underlaget i konversationen.",
                ],
            }
        )

        assert render_confirmed_requirements_proposal_prompt_block(payload) == "- none"


# The v23 disclosure identity, pinned. A confirmation names a disclosure by
# this hash, so the hash of a card already shown must never move: not when the
# payload grows a field outside the hashed content (the displayed-instance
# token), and not when a nested payload model changes shape. Each card below
# exercises every nested model the identity serializes; the literals were
# computed on the parent commit and are never regenerated.
_V23_MINIMAL_CARD: dict[str, object] = {
    "summary": "Ett flöde som sammanfattar ärenden.",
    "key_decisions": [],
    "input_description": "Ett ärende i PDF-form.",
    "output_description": "En kort sammanfattning.",
}
_V23_MINIMAL_CARD_VERSION = (
    "5946941a4dda583c32ac7006f256e5661dbefd77e854723247bc160a3fd1938a"
)

_V23_FULL_CARD: dict[str, object] = {
    "summary": "Läser protokoll och skriver ett beslutsunderlag – på svenska.",
    "key_decisions": [
        {
            "topic": "Resultat",
            "decision": "Word-dokument",
            "question_id": "terminal_output",
            "is_derived": False,
        },
        {"topic": "Underlag", "decision": "Ett protokoll per körning"},
    ],
    "input_description": "Ett uppladdat protokoll.",
    "output_description": "Ett beslutsunderlag som Word-dokument.",
    "assumptions": ["Protokollen är läsbara."],
    "assumption_rows": [
        {
            "question_id": "document_material_scope",
            "slot_name": "document_material_scope",
            "value": "single_document_case",
            "topic": "Underlag",
            "label": "Ett huvuddokument per ärende",
        }
    ],
    "manual_setup_notes": ["Koppla kunskapsbasen med mallar."],
    "resolved_requirements": [
        {"requirement_id": "terminal_output", "selected_value": "docx_document"},
        {"requirement_id": "docx_output_mode", "selected_value": "template_fill"},
    ],
    "attachment_rows": [
        {
            "file_id": "0190a7a2-6f1e-7c3a-9b2d-3c4d5e6f7a8b",
            "filename": "mall.docx",
            "role": "template",
            "readable": True,
            "coverage": "fully_seen",
            "travels": True,
            "placeholders": ["beslut", "datum"],
        },
        {
            "file_id": "0190a7a2-6f1e-7c3a-9b2d-3c4d5e6f7a8c",
            "filename": "exempel.pdf",
            "role": "example_output",
            "readable": True,
            "coverage": "excerpt_truncated",
            "travels": False,
        },
    ],
    "run_preview": {
        "runtime_input": "single_document_case",
        "runtime_input_label": "Ett dokument per körning",
        "max_files": 1,
        "result_type": "docx_document",
        "result_type_label": "Word-dokument",
        "report_layout": "sectioned",
        "report_layout_label": "Med rubriker",
        "template": {
            "filename": "mall.docx",
            "placeholder_count": 2,
            "origin": "session",
        },
    },
}
_V23_FULL_CARD_VERSION = (
    "49d5e355ba23d5469423acab3d255ca6080734de4e51b3da0e2eebe3e4db747c"
)


class TestV23DisclosureIdentity:
    def test_the_hashed_fields_are_the_frozen_v23_set(self) -> None:
        # Extending the hashed content is a new identity, not an edit of this
        # one: every stored confirmation would stop matching its card. The
        # model and the frozen set agree, so no disclosure field is unhashed.
        assert set(RequirementsDisclosureContent.model_fields) == (
            V23_DISCLOSURE_IDENTITY_FIELDS
        )
        assert V23_DISCLOSURE_IDENTITY_FIELDS == {
            "summary",
            "key_decisions",
            "input_description",
            "output_description",
            "assumptions",
            "assumption_rows",
            "manual_setup_notes",
            "resolved_requirements",
            "attachment_rows",
            "run_preview",
        }

    def test_minimal_card_keeps_its_golden_version(self) -> None:
        content = RequirementsDisclosureContent.model_validate(_V23_MINIMAL_CARD)

        assert build_requirements_version(content) == _V23_MINIMAL_CARD_VERSION

    def test_card_with_every_nested_payload_keeps_its_golden_version(self) -> None:
        content = RequirementsDisclosureContent.model_validate(_V23_FULL_CARD)

        assert build_requirements_version(content) == _V23_FULL_CARD_VERSION

    def test_display_fields_beside_the_content_do_not_move_the_version(
        self,
    ) -> None:
        # Everything a summary payload carries beside the hashed content is
        # display: the names projection, the run-form projection, weak-role
        # provenance and the displayed-instance token.
        payload = RequirementsSummaryPayload.model_validate(
            {
                **_V23_FULL_CARD,
                "requirements_version": _V23_FULL_CARD_VERSION,
                "weak_role_file_ids": ["0190a7a2-6f1e-7c3a-9b2d-3c4d5e6f7a8c"],
                "named_content_fields": [
                    {
                        "id": "beslut",
                        "label": "beslut",
                        "name": "beslut",
                        "segments": [],
                        "unplaced": False,
                        "can_contain_fields": False,
                    }
                ],
                "runtime_input_fields": [
                    {
                        "key": "diarienummer",
                        "label": "Diarienummer",
                        "type": "text",
                        "required": True,
                        "purpose": "Tolka underlaget",
                    }
                ],
                "instance_token": "7d0c6c1e-3f7a-4a51-9d7e-2b8f0c4e5a61",
            }
        )

        assert payload.instance_token is not None
        assert build_requirements_version(payload) == _V23_FULL_CARD_VERSION
