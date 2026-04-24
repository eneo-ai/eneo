"""Contract tests for `AttachmentObservation` and its nested models.

Pin the Pydantic surface callers rely on:

- construction requires the full set of mandatory fields,
- boundary rules (sha256 length/charset, unit-interval scores, positive
  version stamps, literal membership, non-empty rationale) reject
  invalid input loudly,
- strict `extra="forbid"` protects JSONB payloads from field drift,
- `validated_snapshot()` revalidates container mutations before the
  save path so list/dict edits cannot silently poison the cache,
- a full observation round-trips through `model_dump(mode="json")` →
  `model_validate(...)` unchanged.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.attachment_observation import (
    AttachmentObservation,
    AttachmentStructure,
    DeterministicSignals,
    FormFieldSignal,
    Heading,
    PlannerImplication,
    StructuredFallback,
    TableDimension,
)


def _minimal_structure() -> AttachmentStructure:
    return AttachmentStructure(
        has_placeholders=False,
        has_form_fields=False,
        has_sections=False,
        has_tables=False,
        has_hierarchy=False,
        has_unfilled_fields=False,
    )


def _minimal_observation() -> AttachmentObservation:
    return AttachmentObservation(
        tenant_id=uuid4(),
        content_sha256="a" * 64,
        digest_version=1,
        fcm_version=1,
        pattern_registry_version=4,
        kind="reference",
        structure=_minimal_structure(),
        digest_text="one paragraph describing a generic reference document",
        token_count=128,
    )


class TestAttachmentObservationShape:
    def test_minimal_observation_accepted(self):
        obs = _minimal_observation()

        assert obs.content_sha256 == "a" * 64
        assert obs.digest_version == 1
        assert obs.fcm_version == 1
        assert obs.pattern_registry_version == 4
        assert obs.kind == "reference"
        assert obs.structured_fallback is None
        assert obs.likely_planner_implications == []
        assert obs.missing_info_cues == []
        assert obs.capability_relevance == {}
        assert obs.likely_questions_triggered == []
        assert obs.token_count == 128

    def test_content_sha256_must_be_64_lowercase_hex(self):
        with pytest.raises(ValidationError):
            AttachmentObservation(
                tenant_id=uuid4(),
                content_sha256="short",
                digest_version=1,
                fcm_version=1,
                pattern_registry_version=4,
                kind="reference",
                structure=_minimal_structure(),
                digest_text="text",
                token_count=1,
            )

    def test_content_sha256_rejects_uppercase(self):
        with pytest.raises(ValidationError):
            AttachmentObservation(
                tenant_id=uuid4(),
                content_sha256="A" * 64,
                digest_version=1,
                fcm_version=1,
                pattern_registry_version=4,
                kind="reference",
                structure=_minimal_structure(),
                digest_text="text",
                token_count=1,
            )

    def test_content_sha256_rejects_non_hex(self):
        with pytest.raises(ValidationError):
            AttachmentObservation(
                tenant_id=uuid4(),
                content_sha256="z" * 64,
                digest_version=1,
                fcm_version=1,
                pattern_registry_version=4,
                kind="reference",
                structure=_minimal_structure(),
                digest_text="text",
                token_count=1,
            )

    @pytest.mark.parametrize("bad_version", [0, -1])
    def test_version_stamps_must_be_positive(self, bad_version):
        for field_name in ("digest_version", "fcm_version", "pattern_registry_version"):
            kwargs: dict[str, object] = {
                "tenant_id": uuid4(),
                "content_sha256": "a" * 64,
                "digest_version": 1,
                "fcm_version": 1,
                "pattern_registry_version": 4,
                "kind": "reference",
                "structure": _minimal_structure(),
                "digest_text": "text",
                "token_count": 1,
            }
            kwargs[field_name] = bad_version
            with pytest.raises(ValidationError):
                AttachmentObservation(**kwargs)

    def test_kind_literal_membership_enforced(self):
        with pytest.raises(ValidationError):
            AttachmentObservation(
                tenant_id=uuid4(),
                content_sha256="a" * 64,
                digest_version=1,
                fcm_version=1,
                pattern_registry_version=4,
                kind="unknown_kind",  # type: ignore[arg-type]
                structure=_minimal_structure(),
                digest_text="text",
                token_count=1,
            )

    def test_token_count_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            AttachmentObservation(
                tenant_id=uuid4(),
                content_sha256="a" * 64,
                digest_version=1,
                fcm_version=1,
                pattern_registry_version=4,
                kind="reference",
                structure=_minimal_structure(),
                digest_text="text",
                token_count=-1,
            )

    def test_capability_relevance_values_must_be_in_unit_interval(self):
        with pytest.raises(ValidationError):
            AttachmentObservation(
                tenant_id=uuid4(),
                content_sha256="a" * 64,
                digest_version=1,
                fcm_version=1,
                pattern_registry_version=4,
                kind="reference",
                structure=_minimal_structure(),
                digest_text="text",
                token_count=1,
                capability_relevance={"summarize_text": 1.5},
            )
        with pytest.raises(ValidationError):
            AttachmentObservation(
                tenant_id=uuid4(),
                content_sha256="a" * 64,
                digest_version=1,
                fcm_version=1,
                pattern_registry_version=4,
                kind="reference",
                structure=_minimal_structure(),
                digest_text="text",
                token_count=1,
                capability_relevance={"summarize_text": -0.1},
            )

    def test_capability_relevance_mid_values_accepted(self):
        obs = AttachmentObservation(
            tenant_id=uuid4(),
            content_sha256="a" * 64,
            digest_version=1,
            fcm_version=1,
            pattern_registry_version=4,
            kind="reference",
            structure=_minimal_structure(),
            digest_text="text",
            token_count=1,
            capability_relevance={
                "summarize_text": 0.75,
                "extract_structured_fields": 0.1,
            },
        )
        assert obs.capability_relevance == {
            "summarize_text": 0.75,
            "extract_structured_fields": 0.1,
        }

    def test_extra_field_rejected_on_every_model(self):
        with pytest.raises(ValidationError):
            AttachmentObservation.model_validate(
                {
                    "tenant_id": str(uuid4()),
                    "content_sha256": "a" * 64,
                    "digest_version": 1,
                    "fcm_version": 1,
                    "pattern_registry_version": 4,
                    "kind": "reference",
                    "structure": _minimal_structure().model_dump(),
                    "digest_text": "text",
                    "token_count": 1,
                    "surprise_field": "unknown",
                }
            )


class TestPlannerImplication:
    def test_confidence_must_be_in_unit_interval(self):
        with pytest.raises(ValidationError):
            PlannerImplication(
                suggested_pattern_id="single_step_summarize",
                confidence=1.5,
                reason="matches summarize pattern",
            )
        with pytest.raises(ValidationError):
            PlannerImplication(
                suggested_pattern_id="single_step_summarize",
                confidence=-0.1,
                reason="matches summarize pattern",
            )

    def test_reason_must_be_non_empty(self):
        with pytest.raises(ValidationError):
            PlannerImplication(
                suggested_pattern_id="single_step_summarize",
                confidence=0.8,
                reason="   ",
            )

    def test_accepts_valid(self):
        imp = PlannerImplication(
            suggested_pattern_id="single_step_summarize",
            confidence=0.85,
            reason="document has dense prose and no structured fields",
        )
        assert imp.confidence == 0.85


class TestStructuredFallback:
    @pytest.mark.parametrize("mode", ["dense_text", "structural_schema"])
    def test_accepts_declared_modes(self, mode):
        fallback = StructuredFallback(mode=mode, content="body")
        assert fallback.mode == mode

    def test_rejects_unknown_mode(self):
        with pytest.raises(ValidationError):
            StructuredFallback(mode="novel_mode", content="body")  # type: ignore[arg-type]


class TestDeterministicSignals:
    def test_minimal_signals_accepted(self):
        signals = DeterministicSignals(
            mime_type="application/pdf",
            extension="pdf",
            size_bytes=1024,
        )
        assert signals.page_count is None
        assert signals.table_dimensions == []
        assert signals.form_fields == []
        assert signals.placeholder_tokens == []

    def test_size_bytes_non_negative(self):
        with pytest.raises(ValidationError):
            DeterministicSignals(
                mime_type="application/pdf",
                extension="pdf",
                size_bytes=-1,
            )

    def test_heading_level_bounds(self):
        with pytest.raises(ValidationError):
            Heading(level=0, text="h0")
        with pytest.raises(ValidationError):
            Heading(level=7, text="h7")

    def test_table_dimensions_non_negative(self):
        with pytest.raises(ValidationError):
            TableDimension(rows=-1, cols=1)
        with pytest.raises(ValidationError):
            TableDimension(rows=1, cols=-1)
        td = TableDimension(rows=0, cols=0)
        assert td.rows == 0

    def test_form_field_signal_allows_missing_default_and_placeholder(self):
        fs = FormFieldSignal(name="deadline", field_type="date")
        assert fs.default is None
        assert fs.placeholder is None

    def test_full_signals_roundtrip(self):
        signals = DeterministicSignals(
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            extension="docx",
            size_bytes=8192,
            page_count=4,
            heading_tree=[
                Heading(level=1, text="Intro"),
                Heading(level=2, text="Scope"),
            ],
            section_count=2,
            table_count=1,
            table_dimensions=[TableDimension(rows=3, cols=2)],
            form_fields=[
                FormFieldSignal(
                    name="applicant", field_type="text", placeholder="name"
                ),
            ],
            placeholder_tokens=["{{applicant}}", "{{deadline}}"],
            is_scanned_pdf=False,
            bullet_density=0.2,
        )
        roundtrip = DeterministicSignals.model_validate(signals.model_dump(mode="json"))
        assert roundtrip == signals


class TestRoundTripAndSnapshot:
    def test_full_observation_roundtrip_through_json(self):
        obs = AttachmentObservation(
            tenant_id=uuid4(),
            content_sha256="f" * 64,
            digest_version=1,
            fcm_version=1,
            pattern_registry_version=4,
            kind="template",
            structure=AttachmentStructure(
                has_placeholders=True,
                has_form_fields=False,
                has_sections=True,
                has_tables=False,
                has_hierarchy=True,
                has_unfilled_fields=True,
            ),
            digest_text="docx template with two placeholders {{applicant}} and {{deadline}}",
            structured_fallback=StructuredFallback(
                mode="structural_schema",
                content='{"placeholders": ["applicant", "deadline"]}',
            ),
            likely_planner_implications=[
                PlannerImplication(
                    suggested_pattern_id="document_to_docx_template_fill",
                    confidence=0.9,
                    reason="docx with placeholder tokens implies template_fill",
                ),
            ],
            missing_info_cues=["applicant has no default"],
            capability_relevance={
                "document_to_docx_template": 0.95,
                "summarize_text": 0.1,
            },
            likely_questions_triggered=["primary_runtime_input"],
            token_count=480,
        )

        restored = AttachmentObservation.model_validate(obs.model_dump(mode="json"))
        assert restored == obs

    def test_validated_snapshot_catches_container_mutation(self):
        obs = _minimal_observation()
        obs.missing_info_cues.append("  ")
        obs.capability_relevance["summarize_text"] = 2.0
        with pytest.raises(ValidationError):
            obs.validated_snapshot()

    def test_validated_snapshot_returns_equal_copy_when_clean(self):
        obs = _minimal_observation()
        snap = obs.validated_snapshot()
        assert snap == obs
        assert snap is not obs
