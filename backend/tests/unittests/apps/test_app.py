from unittest.mock import MagicMock

import pytest

from intric.apps.apps.api.app_models import InputFieldType
from intric.apps.apps.app import App
from intric.files.audio import AudioMimeTypes
from intric.files.image import ImageMimeTypes
from intric.files.text import TextMimeTypes
from intric.main.exceptions import BadRequestException


@pytest.fixture
def app():
    return App(
        created_at=MagicMock(),
        updated_at=MagicMock(),
        id=None,
        tenant_id=MagicMock(),
        user_id=MagicMock(),
        space_id=MagicMock(),
        name=MagicMock(),
        description=None,
        prompt=None,
        completion_model=MagicMock(),
        completion_model_kwargs=MagicMock(),
        input_fields=[],
        attachments=[],
        published=False,
        transcription_model=None,
    )


def test_can_not_have_more_than_one_input_field(
    app: App,
):
    with pytest.raises(BadRequestException):
        app.update(input_fields=[MagicMock(), MagicMock()])


def test_can_have_one_input(app: App):
    input_field = MagicMock()

    app.update(input_fields=[input_field])

    assert app.input_fields == [input_field]


@pytest.mark.parametrize(
    [
        "type",
        "mimetypes",
        "is_valid_input",
    ],
    [
        [InputFieldType.TEXT_FIELD, TextMimeTypes.values(), False],
        [InputFieldType.TEXT_FIELD, AudioMimeTypes.values(), False],
        [InputFieldType.TEXT_FIELD, ImageMimeTypes.values(), False],
        [InputFieldType.TEXT_UPLOAD, TextMimeTypes.values(), True],
        [InputFieldType.TEXT_UPLOAD, AudioMimeTypes.values(), False],
        [InputFieldType.TEXT_UPLOAD, ImageMimeTypes.values(), False],
        [InputFieldType.AUDIO_UPLOAD, TextMimeTypes.values(), False],
        [InputFieldType.AUDIO_UPLOAD, AudioMimeTypes.values(), True],
        [InputFieldType.AUDIO_UPLOAD, ImageMimeTypes.values(), False],
        [InputFieldType.AUDIO_RECORDER, TextMimeTypes.values(), False],
        [InputFieldType.AUDIO_RECORDER, AudioMimeTypes.values(), True],
        [InputFieldType.AUDIO_RECORDER, ImageMimeTypes.values(), False],
        [InputFieldType.IMAGE_UPLOAD, TextMimeTypes.values(), False],
        [InputFieldType.IMAGE_UPLOAD, AudioMimeTypes.values(), False],
        [InputFieldType.IMAGE_UPLOAD, ImageMimeTypes.values(), True],
    ],
)
def test_input_type_validation(
    app: App,
    type: InputFieldType,
    mimetypes: list[str],
    is_valid_input: bool,
):
    input_field = MagicMock(type=type)
    app.input_fields = [input_field]
    app.transcription_model = MagicMock()

    for mimetype in mimetypes:
        file = MagicMock(mimetype=mimetype, size=0)
        assert app.is_valid_input([file]) is is_valid_input


def test_input_type_with_codec(app: App):
    app.input_fields = [MagicMock(type=InputFieldType.AUDIO_RECORDER)]
    app.transcription_model = MagicMock()

    file = MagicMock(mimetype="audio/webm;codec=opus", size=0)
    assert app.is_valid_input([file])


@pytest.mark.parametrize(
    [
        "type",
        "mimetypes",
        "size",
        "is_valid_input",
    ],
    [
        [InputFieldType.TEXT_UPLOAD, TextMimeTypes.values(), 26214400, True],
        [InputFieldType.TEXT_UPLOAD, TextMimeTypes.values(), 26214400 + 1, False],
        [InputFieldType.AUDIO_UPLOAD, AudioMimeTypes.values(), 209715200, True],
        [InputFieldType.AUDIO_UPLOAD, AudioMimeTypes.values(), 209715200 + 1, False],
        [InputFieldType.IMAGE_UPLOAD, ImageMimeTypes.values(), 20971520, True],
        [InputFieldType.IMAGE_UPLOAD, ImageMimeTypes.values(), 20971520 + 1, False],
    ],
)
def test_input_size_validation(
    app: App,
    type: InputFieldType,
    mimetypes: list[str],
    size: int,
    is_valid_input: bool,
):
    app.input_fields = [MagicMock(type=type)]
    app.transcription_model = MagicMock()

    for mimetype in mimetypes:
        file = MagicMock(mimetype=mimetype, size=size)
        assert app.is_valid_input([file]) is is_valid_input


@pytest.mark.parametrize(
    ["type", "num_files", "mimetype"],
    [
        (InputFieldType.TEXT_UPLOAD, 3, TextMimeTypes.TXT),
        (InputFieldType.AUDIO_UPLOAD, 1, AudioMimeTypes.MP3),
        (InputFieldType.AUDIO_RECORDER, 1, AudioMimeTypes.MP3),
        (InputFieldType.IMAGE_UPLOAD, 2, ImageMimeTypes.PNG),
    ],
)
def test_number_of_files_validation(
    app: App, type: InputFieldType, num_files: int, mimetype: str
):
    app.input_fields = [MagicMock(type=type)]
    app.transcription_model = MagicMock()

    list_of_files = [
        [MagicMock(mimetype=mimetype, size=0) for _ in range(_num_files)]
        for _num_files in range(1, num_files + 1)
    ]

    for files in list_of_files:
        assert app.is_valid_input(files) is True

    too_many_files = [
        MagicMock(mimetype=mimetype, size=0) for _ in range(num_files + 1)
    ]
    assert app.is_valid_input(too_many_files) is False


@pytest.mark.parametrize(
    ["type", "size", "num_files", "is_valid_input"],
    [
        (
            InputFieldType.TEXT_UPLOAD,
            26214400,
            3,
            True,
        ),  # 3 files, 25 MB each, total 75 MB
        (
            InputFieldType.TEXT_UPLOAD,
            26214400,
            4,
            False,
        ),  # 4 files, 25 MB each, total 100 MB
        (
            InputFieldType.TEXT_UPLOAD,
            26214400 + 1,
            1,
            False,
        ),  # 1 file, just over 25 MB
        (InputFieldType.AUDIO_UPLOAD, 209715200, 1, True),  # 1 file, 200 MB
        (
            InputFieldType.AUDIO_UPLOAD,
            209715200,
            2,
            False,
        ),  # 2 files, 200 MB each, total 400 MB
        (
            InputFieldType.AUDIO_UPLOAD,
            209715200 + 1,
            1,
            False,
        ),  # 1 file, just over 200 MB
        (
            InputFieldType.IMAGE_UPLOAD,
            20971520,
            2,
            True,
        ),  # 2 files, 20 MB each, total 40 MB
        (
            InputFieldType.IMAGE_UPLOAD,
            20971520,
            3,
            False,
        ),  # 3 files, 20 MB each, total 60 MB
        (
            InputFieldType.IMAGE_UPLOAD,
            20971520 + 1,
            1,
            False,
        ),  # 1 file, just over 20 MB
    ],
)
def test_total_size_of_files_validation(
    app: App, type: InputFieldType, size: int, num_files: int, is_valid_input: bool
):
    mimetype = {
        InputFieldType.TEXT_UPLOAD: TextMimeTypes.TXT,
        InputFieldType.AUDIO_UPLOAD: AudioMimeTypes.MP3,
        InputFieldType.IMAGE_UPLOAD: ImageMimeTypes.PNG,
    }[type]

    files = [MagicMock(size=size, mimetype=mimetype) for _ in range(num_files)]
    app.input_fields = [MagicMock(type=type)]
    app.transcription_model = MagicMock()
    assert app.is_valid_input(files) is is_valid_input


@pytest.mark.parametrize(
    ["type", "text", "is_valid_input"],
    [
        (InputFieldType.TEXT_FIELD, "a" * 10000, True),  # Exactly 10000 characters
        (InputFieldType.TEXT_FIELD, "a" * 10001, False),  # Just over 10000 characters
        (InputFieldType.TEXT_FIELD, "", False),  # Empty text
        (InputFieldType.TEXT_UPLOAD, "a" * 10000, False),
        (InputFieldType.AUDIO_UPLOAD, "a" * 10000, False),
        (InputFieldType.AUDIO_RECORDER, "a" * 10000, False),
        (InputFieldType.IMAGE_UPLOAD, "a" * 10000, False),
    ],
)
def test_input_text_validation(
    app: App, type: InputFieldType, text: str, is_valid_input: bool
):
    app.input_fields = [MagicMock(type=type)]

    assert app.is_valid_input([], text) is is_valid_input
