from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from intric.ai_models.completion_models.completion_model import (
    CompletionModelFamily,
    ModelHostingLocation,
    ModelKwargs,
    ModelStability,
)
from intric.ai_models.model_enums import ModelFamily
from intric.apps.apps.api import app_assembler as app_assembler_module
from intric.apps.apps.api.app_assembler import (
    AppAssembler,
    _AUDIO_MAX_FILES,
    _IMAGE_MAX_FILES,
    _TEXT_MAX_FILES,
)
from intric.apps.apps.api.app_models import InputField, InputFieldType
from intric.apps.apps.app import App
from intric.completion_models.domain import CompletionModel
from intric.files.audio import AudioMimeTypes
from intric.files.file_models import AcceptedFileType, Limit
from intric.files.image import ImageMimeTypes
from intric.files.text import TextMimeTypes
from intric.transcription_models.domain import TranscriptionModel
from tests.fixtures import TEST_USER, TEST_UUID

# ── Test-specific settings ────────────────────────────────────────────────

CUSTOM_TEXT_LIMIT = 5_000_000  # 5 MB
CUSTOM_IMAGE_LIMIT = 8_000_000  # 8 MB
CUSTOM_AUDIO_LIMIT = 150_000_000  # 150 MB

_FAKE_SETTINGS = SimpleNamespace(
    upload_file_to_session_max_size=CUSTOM_TEXT_LIMIT,
    upload_image_to_session_max_size=CUSTOM_IMAGE_LIMIT,
    transcription_max_file_size=CUSTOM_AUDIO_LIMIT,
)


# ── Expected values derived from settings ────────────────────────────────

def _text_uploads(limit: int = CUSTOM_TEXT_LIMIT):
    return [AcceptedFileType(mimetype=m, size_limit=limit) for m in TextMimeTypes.values()]


def _image_uploads(limit: int = CUSTOM_IMAGE_LIMIT):
    return [AcceptedFileType(mimetype=m, size_limit=limit) for m in ImageMimeTypes.values()]


def _audio_uploads(limit: int = CUSTOM_AUDIO_LIMIT):
    return [AcceptedFileType(mimetype=m, size_limit=limit) for m in AudioMimeTypes.values()]


# ── Fixtures ─────────────────────────────────────────────────────────────

TEST_NAME = "Test name"
TEST_COMPLETION_MODEL = CompletionModel(
    user=TEST_USER,
    id=TEST_UUID,
    name=TEST_NAME,
    nickname=TEST_NAME,
    family=CompletionModelFamily.OPEN_AI,
    max_input_tokens=1000,
    max_output_tokens=256,
    is_deprecated=False,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    vision=False,
    reasoning=False,
    is_org_enabled=True,
    is_org_default=False,
    created_at=None,
    updated_at=None,
    org=None,
    open_source=False,
    description=None,
    nr_billion_parameters=None,
    hf_link=None,
    deployment_name=None,
)
TEST_TRANSCRIPTION_MODEL = TranscriptionModel(
    user=TEST_USER,
    id=TEST_UUID,
    name=TEST_NAME,
    nickname=TEST_NAME,
    family=ModelFamily.OPEN_AI,
    is_deprecated=False,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    open_source=False,
    description=None,
    hf_link=None,
    org=None,
    is_org_enabled=True,
    is_org_default=False,
    created_at=None,
    updated_at=None,
    base_url=None,
)


@pytest.fixture
def assembler(monkeypatch):
    monkeypatch.setattr(app_assembler_module, "get_settings", lambda: _FAKE_SETTINGS)
    return AppAssembler(prompt_assembler=MagicMock())


@pytest.fixture
def app():
    app = MagicMock(
        id=TEST_UUID,
        user_id=TEST_UUID,
        tenant_id=TEST_UUID,
        description=None,
        input_fields=[],
        attachments=[],
        prompt=None,
        completion_model=TEST_COMPLETION_MODEL,
        completion_model_kwargs=ModelKwargs(),
        transcription_model=TEST_TRANSCRIPTION_MODEL,
        icon_id=None,
    )
    app.name = TEST_NAME
    return app


# ── Tests: accepted file types come from config ─────────────────────────


@pytest.mark.parametrize(
    ["input_field_type", "expected_accepted_file_types"],
    [
        [InputFieldType.TEXT_FIELD, []],
        [InputFieldType.TEXT_UPLOAD, _text_uploads()],
        [InputFieldType.AUDIO_UPLOAD, _audio_uploads()],
        [InputFieldType.AUDIO_RECORDER, _audio_uploads()],
        [InputFieldType.IMAGE_UPLOAD, _image_uploads()],
    ],
)
def test_get_accepted_file_types(
    app: App,
    assembler: AppAssembler,
    input_field_type,
    expected_accepted_file_types,
):
    app.input_fields = [InputField(type=input_field_type)]

    app_public = assembler.from_app_to_model(app)

    assert app_public.input_fields[0].accepted_file_types == expected_accepted_file_types


# ── Tests: limits come from config ───────────────────────────────────────


@pytest.mark.parametrize(
    ["input_field_type", "expected_limit"],
    [
        [InputFieldType.TEXT_FIELD, Limit(max_files=0, max_size=0)],
        [
            InputFieldType.TEXT_UPLOAD,
            Limit(max_files=_TEXT_MAX_FILES, max_size=_TEXT_MAX_FILES * CUSTOM_TEXT_LIMIT),
        ],
        [
            InputFieldType.AUDIO_UPLOAD,
            Limit(max_files=_AUDIO_MAX_FILES, max_size=_AUDIO_MAX_FILES * CUSTOM_AUDIO_LIMIT),
        ],
        [
            InputFieldType.AUDIO_RECORDER,
            Limit(max_files=_AUDIO_MAX_FILES, max_size=_AUDIO_MAX_FILES * CUSTOM_AUDIO_LIMIT),
        ],
        [
            InputFieldType.IMAGE_UPLOAD,
            Limit(max_files=_IMAGE_MAX_FILES, max_size=_IMAGE_MAX_FILES * CUSTOM_IMAGE_LIMIT),
        ],
    ],
)
def test_get_limit(
    app: App,
    assembler: AppAssembler,
    input_field_type,
    expected_limit,
):
    app.input_fields = [InputField(type=input_field_type)]

    app_public = assembler.from_app_to_model(app)

    assert app_public.input_fields[0].limit == expected_limit


# ── Tests: allowed_attachments come from config ──────────────────────────


def test_attachment_formats(app: App, assembler: AppAssembler):
    app_public = assembler.from_app_to_model(app)

    assert app_public.allowed_attachments.accepted_file_types == _text_uploads()
    assert app_public.allowed_attachments.limit == Limit(
        max_files=_TEXT_MAX_FILES,
        max_size=_TEXT_MAX_FILES * CUSTOM_TEXT_LIMIT,
    )


# ── Tests: changing settings changes limits ──────────────────────────────


def test_limits_change_when_settings_change(monkeypatch, app):
    """Prove that assembler reads from config at call time, not from hardcoded values."""
    new_audio_limit = 500_000_000  # 500 MB
    settings = SimpleNamespace(
        upload_file_to_session_max_size=CUSTOM_TEXT_LIMIT,
        upload_image_to_session_max_size=CUSTOM_IMAGE_LIMIT,
        transcription_max_file_size=new_audio_limit,
    )
    monkeypatch.setattr(app_assembler_module, "get_settings", lambda: settings)

    assembler = AppAssembler(prompt_assembler=MagicMock())
    app.input_fields = [InputField(type=InputFieldType.AUDIO_UPLOAD)]

    app_public = assembler.from_app_to_model(app)

    assert app_public.input_fields[0].accepted_file_types == _audio_uploads(new_audio_limit)
    assert app_public.input_fields[0].limit == Limit(
        max_files=_AUDIO_MAX_FILES,
        max_size=_AUDIO_MAX_FILES * new_audio_limit,
    )
