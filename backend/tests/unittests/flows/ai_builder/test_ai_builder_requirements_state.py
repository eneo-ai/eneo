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
    build_requirements_version,
    latest_confirmed_requirements,
    render_confirmed_requirements_proposal_prompt_block,
    render_confirmed_requirements_system_prompt_block,
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
    def test_confirmed_requirements_prompt_omits_default_review_boilerplate(
        self,
    ) -> None:
        payload = _disclosure(
            {
                "summary": (
                    "Jag har tillräckligt med information för att ta fram ett "
                    "förslag till flödesplan. Granska sammanfattningen innan "
                    "planen byggs."
                ),
                "key_decisions": [
                    {"topic": "Bearbetning", "decision": "Översätt text till text"},
                ],
                "input_description": "Primär indata vid körning behöver granskas.",
                "output_description": "Huvudsakligt slutresultat behöver granskas.",
                "assumptions": [
                    "Planen ska följa kraven och underlaget i konversationen.",
                    "Användaren ska kunna granska och ändra planen innan den tillämpas.",
                    "Ingen extra metadata ska samlas in vid körning.",
                ],
                "manual_setup_notes": [
                    "The user can review and change the plan before it is applied.",
                    "Koppla standardmodellen för textsteg.",
                ],
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
        ]

        summary = latest_confirmed_requirements(conversation)
        assert summary is not None
        prompt_block = render_confirmed_requirements_system_prompt_block(summary)

        assert "Granska sammanfattningen innan planen byggs" not in prompt_block
        assert "Primär indata vid körning behöver granskas" not in prompt_block
        assert "Huvudsakligt slutresultat behöver granskas" not in prompt_block
        assert "Användaren ska kunna granska" not in prompt_block
        assert "Översätt text till text" in prompt_block
        assert "Koppla standardmodellen för textsteg" in prompt_block
        assert "### Innehåll som resultatet ska bevara\n- beslut" in prompt_block

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

    def test_prompt_block_carries_the_typed_attachment_rows_and_run_contract(self):
        """The rows and preview replaced the attachment prose on the card; the
        planner is handed the same facts from the types."""
        from uuid import uuid4

        from eneo.flows.ai_builder.ai_builder_event_models import (
            AttachmentRowPayload,
            RunPreviewPayload,
            RunPreviewTemplatePayload,
        )

        payload = _disclosure(
            {
                "summary": "Fyll i kommunens mall.",
                "key_decisions": [],
                "input_description": "Dokument vid körning.",
                "output_description": "Ifylld mall.",
                "assumptions": [],
            }
        ).model_copy(
            update={
                "attachment_rows": [
                    AttachmentRowPayload(
                        file_id=uuid4(),
                        filename="mall.docx",
                        role="template",
                        readable=True,
                        coverage="fully_seen",
                        travels=True,
                        placeholders=["namn", "datum"],
                    ),
                    AttachmentRowPayload(
                        file_id=uuid4(),
                        filename="underlag.pdf",
                        role="reference_material",
                        readable=False,
                        coverage="inventory_only",
                        travels=False,
                    ),
                ],
                "run_preview": RunPreviewPayload(
                    runtime_input="documents",
                    max_files=5,
                    result_type="docx",
                    report_layout=None,
                    template=RunPreviewTemplatePayload(
                        filename="mall.docx", placeholder_count=2
                    ),
                ),
            }
        )
        prompt_block = render_confirmed_requirements_proposal_prompt_block(payload)
        assert prompt_block == "\n".join(
            (
                "- summary: Fyll i kommunens mall.",
                "- input_description: Dokument vid körning.",
                "- output_description: Ifylld mall.",
                "- attachments:",
                "  - mall.docx: role=template; coverage=fully_seen; travels_with_run; "
                "placeholders=namn, datum",
                "  - underlag.pdf: role=reference_material; coverage=inventory_only; "
                "planning_only; unreadable",
                "- run_contract:",
                "  - runtime_input: documents",
                "  - max_files: 5",
                "  - result_type: docx",
                "  - template: mall.docx",
            )
        )
        assert "Koppla transkriberingsmodellen" not in prompt_block

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
