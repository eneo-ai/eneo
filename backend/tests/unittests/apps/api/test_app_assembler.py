from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from eneo.ai_models.completion_models.completion_model import (
    ModelKwargs,
)
from eneo.apps.apps.api.app_assembler import (
    _AUDIO_MAX_FILES,
    _IMAGE_MAX_FILES,
    _TEXT_MAX_FILES,
    AppAssembler,
)
from eneo.apps.apps.api.app_models import InputField, InputFieldType
from eneo.apps.apps.app import App
from eneo.completion_models.domain import CompletionModel
from eneo.files.audio import AudioMimeTypes
from eneo.files.file_models import AcceptedFileType, Limit
from eneo.files.image import ImageMimeTypes
from eneo.files.mime_support import supported_text_mimes
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from eneo.transcription_models.domain import TranscriptionModel
from tests.fixtures import TEST_USER, TEST_UUID

# ── Test-specific settings ────────────────────────────────────────────────

CUSTOM_TEXT_LIMIT = 5_000_000  # 5 MB
CUSTOM_IMAGE_LIMIT = 8_000_000  # 8 MB
CUSTOM_AUDIO_LIMIT = 150_000_000  # 150 MB

_UPLOAD_ADMISSION = UploadAdmissionSnapshot(
    policy_revision=4,
    session_storage_target=StorageKind.POSTGRES_INLINE,
    session_operator_ceiling_bytes=200_000_000,
    session_file_maximum_bytes=CUSTOM_TEXT_LIMIT,
    session_image_maximum_bytes=CUSTOM_IMAGE_LIMIT,
    session_audio_maximum_bytes=CUSTOM_AUDIO_LIMIT,
    knowledge_file_maximum_bytes=25_000_000,
    knowledge_audio_maximum_bytes=200_000_000,
)


# ── Expected values derived from settings ────────────────────────────────


def _text_uploads(limit: int = CUSTOM_TEXT_LIMIT):
    return [
        AcceptedFileType(mimetype=m, size_limit=limit) for m in supported_text_mimes()
    ]


def _image_uploads(limit: int = CUSTOM_IMAGE_LIMIT):
    return [
        AcceptedFileType(mimetype=m, size_limit=limit) for m in ImageMimeTypes.values()
    ]


def _audio_uploads(limit: int = CUSTOM_AUDIO_LIMIT):
    return [
        AcceptedFileType(mimetype=m, size_limit=limit) for m in AudioMimeTypes.values()
    ]


# ── Fixtures ─────────────────────────────────────────────────────────────

TEST_NAME = "Test name"
TEST_COMPLETION_MODEL = CompletionModel(
    tenant=TEST_USER.tenant,
    id=TEST_UUID,
    name=TEST_NAME,
    nickname=TEST_NAME,
    family="openai",
    max_input_tokens=1000,
    max_output_tokens=256,
    is_deprecated=False,
    stability="stable",
    hosting="usa",
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
    tenant=TEST_USER.tenant,
    id=TEST_UUID,
    name=TEST_NAME,
    nickname=TEST_NAME,
    family="openai",
    is_deprecated=False,
    stability="stable",
    hosting="usa",
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
def assembler():
    return AppAssembler(
        user=SimpleNamespace(can_view_model_pricing=True),
        prompt_assembler=MagicMock(),
        upload_admission=_UPLOAD_ADMISSION,
    )


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

    assert (
        app_public.input_fields[0].accepted_file_types == expected_accepted_file_types
    )


# ── Tests: limits come from config ───────────────────────────────────────


@pytest.mark.parametrize(
    ["input_field_type", "expected_limit"],
    [
        [InputFieldType.TEXT_FIELD, Limit(max_files=0, max_size=0)],
        [
            InputFieldType.TEXT_UPLOAD,
            Limit(
                max_files=_TEXT_MAX_FILES, max_size=_TEXT_MAX_FILES * CUSTOM_TEXT_LIMIT
            ),
        ],
        [
            InputFieldType.AUDIO_UPLOAD,
            Limit(
                max_files=_AUDIO_MAX_FILES,
                max_size=_AUDIO_MAX_FILES * CUSTOM_AUDIO_LIMIT,
            ),
        ],
        [
            InputFieldType.AUDIO_RECORDER,
            Limit(
                max_files=_AUDIO_MAX_FILES,
                max_size=_AUDIO_MAX_FILES * CUSTOM_AUDIO_LIMIT,
            ),
        ],
        [
            InputFieldType.IMAGE_UPLOAD,
            Limit(
                max_files=_IMAGE_MAX_FILES,
                max_size=_IMAGE_MAX_FILES * CUSTOM_IMAGE_LIMIT,
            ),
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


def test_new_assembler_uses_new_policy_revision_without_restart(app):
    new_audio_limit = 500_000_000  # 500 MB

    assembler = AppAssembler(
        user=SimpleNamespace(can_view_model_pricing=True),
        prompt_assembler=MagicMock(),
        upload_admission=replace(
            _UPLOAD_ADMISSION,
            policy_revision=_UPLOAD_ADMISSION.policy_revision + 1,
            session_audio_maximum_bytes=new_audio_limit,
        ),
    )
    app.input_fields = [InputField(type=InputFieldType.AUDIO_UPLOAD)]

    app_public = assembler.from_app_to_model(app)

    assert app_public.input_fields[0].accepted_file_types == _audio_uploads(
        new_audio_limit
    )
    assert app_public.input_fields[0].limit == Limit(
        max_files=_AUDIO_MAX_FILES,
        max_size=_AUDIO_MAX_FILES * new_audio_limit,
    )
