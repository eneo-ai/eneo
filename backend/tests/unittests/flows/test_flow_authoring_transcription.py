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
    fill_default_speaker_service,
    kept_speaker_service_id,
    require_chosen_speaker_service,
    require_usable_speaker_service,
    requires_audio_transcription,
    transcription_config_for_write,
)
from eneo.flows.transcription_config import (
    DEFAULT_TRANSCRIPTION_LANGUAGE,
    parse_transcription_config,
)
from eneo.main.exceptions import BadRequestException


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
        return SimpleNamespace(usable_transcription_service=by_id.get)

    @staticmethod
    def _connection() -> SimpleNamespace:
        return SimpleNamespace(id=uuid4())

    @pytest.mark.parametrize("labels", [True, False])
    def test_a_saved_pick_is_kept_whether_or_not_it_labels_speakers(
        self, labels: bool
    ) -> None:
        service_id = uuid4()

        assert (
            kept_speaker_service_id(
                {
                    "wizard": {
                        "transcription_enabled": True,
                        "transcription_diarization": labels,
                        "transcription_speaker_service": {"id": str(service_id)},
                    }
                }
            )
            == service_id
        )

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
        connection = self._connection()

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


_MAPS_SPEAKERS = [SimpleNamespace(output_mode="speaker_mapping")]
_LABELS_OFF = {"transcription_diarization": False}


class TestChosenSpeakerService:
    """Publishing refuses a flow that asks for speaker labels without having
    chosen the service that labels them: nothing is chosen for it."""

    @staticmethod
    def _require(wizard: dict[str, object], steps: list, usable: int) -> None:
        require_chosen_speaker_service(
            parse_transcription_config(
                {"wizard": {"transcription_enabled": True, **wizard}}
            ),
            steps=steps,
            space=SimpleNamespace(  # pyright: ignore[reportArgumentType]
                usable_transcription_services=[object()] * usable
            ),
        )

    @pytest.mark.parametrize(
        ("wizard", "steps", "usable"),
        [
            ({}, _MAPS_SPEAKERS, 0),
            ({}, _MAPS_SPEAKERS, 1),
            (_LABELS_OFF, _MAPS_SPEAKERS, 0),
            ({}, [], 1),
            ({}, [], 2),
        ],
        ids=[
            "step_requires_labels_no_service",
            "step_requires_labels_one_service",
            "step_requires_labels_with_the_setting_off",
            "setting_on_one_service",
            "setting_on_two_services",
        ],
    )
    def test_labels_without_a_chosen_service_are_refused(
        self, wizard: dict[str, object], steps: list, usable: int
    ) -> None:
        with pytest.raises(BadRequestException) as refused:
            self._require(wizard, steps, usable)

        code = FlowGraphIssueCode.FLOW_SPEAKER_SERVICE_NOT_CHOSEN.value
        assert code == "flow_speaker_service_not_chosen"
        assert (refused.value.code, refused.value.context) == (
            code,
            {"issue_code": code},
        )
        # Switching labels off is an answer only while no step needs them.
        assert ("switch speaker identification off" in str(refused.value)) is (
            not steps
        )

    @pytest.mark.parametrize(
        ("wizard", "steps", "usable"),
        [
            ({}, [], 0),
            (_LABELS_OFF, [], 1),
            ({"transcription_speaker_service": {"id": str(uuid4())}}, [], 1),
            (
                {"transcription_speaker_service": {"id": str(uuid4())}},
                _MAPS_SPEAKERS,
                1,
            ),
            ({"transcription_enabled": False}, _MAPS_SPEAKERS, 1),
        ],
        ids=[
            "setting_on_nothing_to_choose",
            "setting_off",
            "chosen",
            "chosen_for_a_step_that_requires_labels",
            "transcribes_nothing",
        ],
    )
    def test_a_flow_that_chose_or_asks_for_no_labels_is_not_refused(
        self, wizard: dict[str, object], steps: list, usable: int
    ) -> None:
        self._require(wizard, steps, usable)


class TestDefaultSpeakerService:
    """A draft that transcribes and whose author has made no choice of
    service is written with the organisation's default as its own choice;
    nothing else is, and a choice of none is a choice."""

    _DEFAULT = uuid4()
    _CHOSEN = {"transcription_speaker_service": {"id": str(uuid4())}}

    @classmethod
    def _fill(
        cls, metadata: dict[str, object] | None, *, default: bool = True
    ) -> dict[str, object] | None:
        return fill_default_speaker_service(
            metadata=metadata,
            space=SimpleNamespace(  # pyright: ignore[reportArgumentType]
                default_transcription_service=SimpleNamespace(id=cls._DEFAULT)
                if default
                else None
            ),
        )

    @pytest.mark.parametrize(
        "wizard", [{}, _LABELS_OFF], ids=["labels_on", "labels_off"]
    )
    def test_the_default_becomes_the_choice_of_a_flow_that_transcribes_and_has_none(
        self, wizard: dict[str, object]
    ) -> None:
        metadata = {
            "form_schema": {"fields": []},
            "wizard": {"transcription_enabled": True, "other": 1, **wizard},
        }
        written = {"form_schema": {"fields": []}, "wizard": dict(metadata["wizard"])}

        filled = self._fill(metadata)

        assert filled == {
            "form_schema": {"fields": []},
            "wizard": {
                **written["wizard"],
                "transcription_speaker_service": {"id": str(self._DEFAULT)},
            },
        }
        # The caller's metadata is not changed in place.
        assert metadata == written

    @pytest.mark.parametrize(
        ("wizard", "default"),
        [
            (_CHOSEN, True),
            ({**_CHOSEN, **_LABELS_OFF}, True),
            ({"transcription_speaker_service": None}, True),
            ({"transcription_speaker_service": None, **_LABELS_OFF}, True),
            ({"transcription_enabled": False}, True),
            ({}, False),
            ({"transcription_diarization": "yes"}, True),
            ({"transcription_speaker_service": {"id": "nope"}}, True),
        ],
        ids=[
            "a_choice_is_kept",
            "a_choice_is_kept_with_labels_off",
            "a_choice_of_none_is_kept",
            "a_choice_of_none_is_kept_with_labels_off",
            "the_flow_transcribes_nothing",
            "the_space_has_no_usable_default",
            "a_malformed_setting_is_left_to_validation",
            "a_malformed_choice_is_left_to_validation",
        ],
    )
    def test_nothing_else_is_filled(
        self, wizard: dict[str, object], default: bool
    ) -> None:
        metadata = {"wizard": {"transcription_enabled": True, **wizard}}

        assert self._fill(metadata, default=default) is metadata

    def test_a_flow_without_metadata_stays_without(self) -> None:
        assert self._fill(None) is None
