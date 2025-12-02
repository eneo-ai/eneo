from unittest.mock import MagicMock

import pytest

from intric.ai_models.completion_models.completion_model import (
    CompletionModelFamily,
    ModelHostingLocation,
    ModelKwargs,
    ModelStability,
)
from intric.ai_models.model_enums import ModelFamily
from intric.apps.apps.api.app_assembler import AppAssembler
from intric.apps.apps.api.app_models import InputField, InputFieldType
from intric.apps.apps.app import App
from intric.completion_models.domain import CompletionModel
from intric.files.audio import AudioMimeTypes
from intric.files.file_models import AcceptedFileType, Limit
from intric.files.image import ImageMimeTypes
from intric.files.text import TextMimeTypes
from intric.transcription_models.domain import TranscriptionModel
from tests.fixtures import TEST_USER, TEST_UUID

TEXT_UPLOADS = [
    AcceptedFileType(mimetype=mimetype, size_limit=26214400) for mimetype in TextMimeTypes.values()
]

IMAGE_UPLOADS = [
    AcceptedFileType(mimetype=mimetype, size_limit=20971520) for mimetype in ImageMimeTypes.values()
]

AUDIO_UPLOADS = [
    AcceptedFileType(mimetype=mimetype, size_limit=209715200)
    for mimetype in AudioMimeTypes.values()
]

TEST_NAME = "Test name"
TEST_COMPLETION_MODEL = CompletionModel(
    user=TEST_USER,
    id=TEST_UUID,
    name=TEST_NAME,
    nickname=TEST_NAME,
    family=CompletionModelFamily.OPEN_AI,
    token_limit=1000,
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
def assembler():
    return AppAssembler(
        prompt_assembler=MagicMock(),
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


@pytest.mark.parametrize(
    ["input_field_type", "expected_accepted_file_types"],
    [
        [InputFieldType.TEXT_FIELD, []],
        [InputFieldType.TEXT_UPLOAD, TEXT_UPLOADS],
        [InputFieldType.AUDIO_UPLOAD, AUDIO_UPLOADS],
        [InputFieldType.AUDIO_RECORDER, AUDIO_UPLOADS],
        [InputFieldType.IMAGE_UPLOAD, IMAGE_UPLOADS],
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


@pytest.mark.parametrize(
    ["input_field_type", "expected_limit"],
    [
        [InputFieldType.TEXT_FIELD, Limit(max_files=0, max_size=0)],
        [
            InputFieldType.TEXT_UPLOAD,
            Limit(
                max_files=3,
                max_size=104857600,
            ),
        ],
        [
            InputFieldType.AUDIO_UPLOAD,
            Limit(max_files=1, max_size=209715200),
        ],
        [InputFieldType.AUDIO_RECORDER, Limit(max_files=1, max_size=209715200)],
        [InputFieldType.IMAGE_UPLOAD, Limit(max_files=2, max_size=41943040)],
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


def test_attachment_formats(app: App, assembler: AppAssembler):
    app_public = assembler.from_app_to_model(app)

    assert app_public.allowed_attachments.accepted_file_types == TEXT_UPLOADS
    assert app_public.allowed_attachments.limit == Limit(max_files=3, max_size=26214400)
