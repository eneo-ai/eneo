"""Tests for Flow authoring transcription defaults."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.flow_step_validation import FlowGraphIssueCode
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    InputSource,
    InputType,
    StepSpec,
)
from eneo.flows.flow_authoring_transcription import (
    apply_audio_transcription_defaults,
    kept_speaker_service_id,
    require_one_speaker_service,
    require_usable_speaker_service,
    requires_audio_transcription,
    transcription_config_for_write,
)
from eneo.flows.transcription_config import (
    DEFAULT_TRANSCRIPTION_LANGUAGE,
    parse_transcription_config,
)
from eneo.main.exceptions import BadRequestException
from eneo.transcription_services.models import TranscriptionOperation


def _step(
    *,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.AUDIO,
) -> StepSpec:
    return StepSpec(
        plan_step_ref="step_a",
        name="Test",
        assistant_spec=AssistantSpec(instructions="Do."),
        input_source=input_source,
        input_type=input_type,
    )


def _steps(*steps: StepSpec) -> list[StepSpec]:
    return list(steps)


class TestTranscriptionSetup:
    """Audio flow_input steps get transcription defaults."""

    def test_audio_flow_input_sets_transcription_enabled(self) -> None:
        result = apply_audio_transcription_defaults(
            metadata=None,
            steps=_steps(_step(input_type=InputType.AUDIO)),
            default_transcription_model_id=uuid4(),
        )

        assert result is not None
        wizard = result["wizard"]
        assert wizard["transcription_enabled"] is True
        assert wizard["transcription_language"] == DEFAULT_TRANSCRIPTION_LANGUAGE
        assert (
            parse_transcription_config(result).language
            == wizard["transcription_language"]
        )

    def test_non_audio_leaves_metadata_unchanged(self) -> None:
        result = apply_audio_transcription_defaults(
            metadata={"existing": "data"},
            steps=_steps(_step(input_type=InputType.DOCUMENT)),
            default_transcription_model_id=uuid4(),
        )

        assert result == {"existing": "data"}


class TestTranscriptionCleanup:
    """When no audio flow_input remains, wizard transcription metadata must be removed."""

    def test_audio_removed_clears_transcription_metadata(self) -> None:
        """After edit changes audio→document, transcription wizard config should be cleared."""
        existing_metadata = {
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(uuid4())},
                "transcription_language": "auto",
                "transcription_speaker_service": {"id": str(uuid4())},
            },
            "form_schema": {"fields": []},
        }

        result = apply_audio_transcription_defaults(
            metadata=existing_metadata,
            steps=_steps(_step(input_type=InputType.DOCUMENT)),
            default_transcription_model_id=uuid4(),
        )

        assert result is not None
        # Transcription keys should be removed from wizard
        wizard = result.get("wizard", {})
        assert "transcription_enabled" not in wizard
        assert "transcription_model" not in wizard
        assert "transcription_language" not in wizard
        assert "transcription_speaker_service" not in wizard

    def test_cleanup_preserves_non_transcription_wizard_data(self) -> None:
        existing_metadata = {
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(uuid4())},
                "transcription_language": "auto",
                "other_setting": "keep_me",
            },
        }

        result = apply_audio_transcription_defaults(
            metadata=existing_metadata,
            steps=_steps(_step(input_type=InputType.DOCUMENT)),
            default_transcription_model_id=None,
        )

        assert result is not None
        wizard = result.get("wizard", {})
        assert wizard.get("other_setting") == "keep_me"
        assert "transcription_enabled" not in wizard

    def test_cleanup_removes_empty_wizard(self) -> None:
        """If wizard only had transcription keys, wizard key itself is cleaned up."""
        existing_metadata = {
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(uuid4())},
                "transcription_language": "sv",
            },
        }

        result = apply_audio_transcription_defaults(
            metadata=existing_metadata,
            steps=_steps(
                _step(input_type=InputType.TEXT, input_source=InputSource.PREVIOUS_STEP)
            ),
            default_transcription_model_id=None,
        )

        # Either wizard is empty/removed, or transcription keys are gone
        if result is not None:
            wizard = result.get("wizard", {})
            assert "transcription_enabled" not in wizard

    def test_no_metadata_no_audio_returns_none(self) -> None:
        result = apply_audio_transcription_defaults(
            metadata=None,
            steps=_steps(_step(input_type=InputType.DOCUMENT)),
            default_transcription_model_id=None,
        )

        assert result is None


class TestStepsTheFlowEndsWith:
    """The requirement is read from each step's own columns, whatever type of
    step value holds them."""

    def test_a_step_view_that_takes_audio_requires_transcription(self) -> None:
        saved = FlowStep(
            id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            assistant_id=uuid4(),
            step_order=1,
            user_description="Lyssna",
            input_source="flow_input",
            input_type="audio",
            output_mode="transcribe_only",
            output_type="text",
        )

        assert requires_audio_transcription([saved]) is True
        assert (
            requires_audio_transcription(
                [saved.model_copy(update={"input_type": "text"})]
            )
            is False
        )


class TestPickedSpeakerService:
    """A picked speaker service must be one the space may use to identify
    speakers."""

    @staticmethod
    def _space(*connections: SimpleNamespace) -> SimpleNamespace:
        by_id = {connection.id: connection for connection in connections}
        return SimpleNamespace(
            usable_transcription_service=by_id.get,
            usable_transcription_services=list(connections),
        )

    @staticmethod
    def _connection(*operations: TranscriptionOperation) -> SimpleNamespace:
        return SimpleNamespace(id=uuid4(), operations=frozenset(operations))

    def test_an_unreadable_saved_pick_names_no_service(self) -> None:
        assert (
            kept_speaker_service_id(
                {
                    "wizard": {
                        "transcription_enabled": True,
                        "transcription_speaker_service": {"id": "nope"},
                    }
                }
            )
            is None
        )

    def test_a_usable_speaker_service_is_accepted(self) -> None:
        connection = self._connection(TranscriptionOperation.DIARIZE)

        require_usable_speaker_service(
            connection.id,
            space=self._space(connection),  # pyright: ignore[reportArgumentType]
        )

    def test_a_service_the_space_may_not_use_is_refused(self) -> None:
        service_id = uuid4()

        with pytest.raises(BadRequestException) as refused:
            require_usable_speaker_service(
                service_id,
                space=self._space(),  # pyright: ignore[reportArgumentType]
            )

        code = FlowGraphIssueCode.FLOW_SPEAKER_SERVICE_UNAVAILABLE.value
        assert refused.value.code == code
        assert refused.value.context == {
            "issue_code": code,
            "speaker_service_id": str(service_id),
        }

    def test_a_service_not_declared_for_speakers_is_refused(self) -> None:
        connection = self._connection(TranscriptionOperation.TRANSCRIBE)

        with pytest.raises(BadRequestException) as refused:
            require_usable_speaker_service(
                connection.id,
                space=self._space(connection),  # pyright: ignore[reportArgumentType]
            )

        assert refused.value.code == (
            FlowGraphIssueCode.FLOW_SPEAKER_SERVICE_CANNOT_IDENTIFY_SPEAKERS.value
        )

    def test_a_malformed_choice_is_refused_when_written(self) -> None:
        with pytest.raises(BadRequestException) as refused:
            transcription_config_for_write(
                {"wizard": {"transcription_speaker_service": {"id": "nope"}}}
            )

        code = FlowGraphIssueCode.FLOW_AUDIO_TRANSCRIPTION_INVALID.value
        assert (refused.value.code, refused.value.context) == (
            code,
            {"issue_code": code},
        )

    @pytest.mark.parametrize("count", [0, 1])
    def test_labels_without_a_pick_need_at_most_one_service(self, count: int) -> None:
        services = [
            self._connection(TranscriptionOperation.DIARIZE) for _ in range(count)
        ]
        # A service that cannot identify speakers is not a candidate.
        services.append(self._connection(TranscriptionOperation.TRANSCRIBE))

        require_one_speaker_service(space=self._space(*services))  # pyright: ignore[reportArgumentType]

    def test_several_speaker_services_need_a_pick(self) -> None:
        space = self._space(
            self._connection(TranscriptionOperation.DIARIZE),
            self._connection(TranscriptionOperation.DIARIZE),
        )

        with pytest.raises(BadRequestException) as refused:
            require_one_speaker_service(space=space)  # pyright: ignore[reportArgumentType]

        assert refused.value.code == (
            FlowGraphIssueCode.FLOW_SPEAKER_SERVICE_CHOICE_REQUIRED.value
        )
