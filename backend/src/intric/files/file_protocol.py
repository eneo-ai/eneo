import os
from pathlib import Path
from typing import Callable

from fastapi import UploadFile

from intric.files.audio import AudioMimeTypes
from intric.files.file_models import FileBaseWithContent, FileType
from intric.files.file_size_service import FileSizeService
from intric.files.image import ImageExtractor, ImageMimeTypes
from intric.files.text import TextExtractor, TextMimeTypes
from intric.main.config import get_settings
from intric.main.exceptions import FileNotSupportedException, FileTooLargeException


def bytes_extractor(filepath: Path, _mimetype: str, _filename: str | None = None):
    with open(filepath, "rb") as file:
        return file.read()


def sanitize_filename(filename: str | None) -> str:
    """Sanitize filename to prevent path traversal attacks."""
    if not filename:
        return "unnamed"

    filename = filename.replace("\x00", "")
    filename = os.path.basename(filename).strip()

    return filename or "unnamed"


class FileProtocol:
    def __init__(
        self,
        file_size_service: FileSizeService,
        text_extractor: TextExtractor,
        image_extractor: ImageExtractor,
    ):
        self.file_size_service = file_size_service
        self.text_extractor = text_extractor
        self.image_extractor = image_extractor

    async def _get_content(
        self,
        upload_file: UploadFile,
        file_type: FileType,
        max_size: int,
        extractor: Callable[[Path, str, str | None], str | bytes],
    ):
        if self.file_size_service.is_too_large(upload_file.file, max_size=max_size):
            raise FileTooLargeException()

        filepath = await self.file_size_service.save_file_to_disk(upload_file.file)
        filepath = Path(filepath)

        try:
            content = extractor(
                filepath, upload_file.content_type, upload_file.filename
            )
            checksum = self.file_size_service.get_file_checksum(filepath)

            if isinstance(content, str):
                size = len(content.encode("utf-8"))
            else:
                size = len(content)

            return self._create_file_base(
                upload_file, file_type, content, checksum, size
            )
        finally:
            os.remove(filepath)

    def _create_file_base(
        self,
        upload_file: UploadFile,
        file_type: FileType,
        content: str | bytes,
        checksum: str,
        size: int,
    ) -> FileBaseWithContent:
        # Sanitize filename to prevent path traversal attacks
        sanitized_filename = sanitize_filename(upload_file.filename)

        file_base_kwargs = {
            "name": sanitized_filename,
            "checksum": checksum,
            "size": size,
            "file_type": file_type,
            "mimetype": upload_file.content_type,
        }

        if file_type == FileType.TEXT:
            file_base_kwargs["text"] = content
        else:
            file_base_kwargs["blob"] = content

        return FileBaseWithContent(**file_base_kwargs)

    async def text_to_domain(
        self, upload_file: UploadFile, max_size: int | None = None
    ):
        if max_size is None:
            max_size = get_settings().upload_file_to_session_max_size

        return await self._get_content(
            upload_file,
            file_type=FileType.TEXT,
            max_size=max_size,
            extractor=self.text_extractor.extract,
        )

    async def image_to_domain(
        self, upload_file: UploadFile, max_size: int | None = None
    ):
        if max_size is None:
            max_size = get_settings().upload_image_to_session_max_size

        return await self._get_content(
            upload_file,
            file_type=FileType.IMAGE,
            max_size=max_size,
            extractor=self.image_extractor.extract,
        )

    async def audio_to_domain(
        self, upload_file: UploadFile, max_size: int | None = None
    ):
        if max_size is None:
            max_size = get_settings().transcription_max_file_size

        return await self._get_content(
            upload_file,
            file_type=FileType.AUDIO,
            max_size=max_size,
            extractor=bytes_extractor,
        )

    async def docx_template_to_domain(
        self, upload_file: UploadFile, max_size: int | None = None
    ) -> FileBaseWithContent:
        if max_size is None:
            max_size = get_settings().upload_file_to_session_max_size

        sanitized_filename = sanitize_filename(upload_file.filename)
        lower_name = sanitized_filename.lower()
        if lower_name.endswith((".docm", ".dotm")):
            raise FileNotSupportedException(
                "DOCX templates must use the .docx format. Macro-enabled Word files are not allowed.",
                code="unsupported_media_type",
                context={"received_type": lower_name.rsplit(".", 1)[-1]},
            )
        if not lower_name.endswith(".docx"):
            raise FileNotSupportedException(
                "Only .docx files can be uploaded as Flow templates.",
                code="unsupported_media_type",
                context={
                    "received_type": (
                        lower_name.rsplit(".", 1)[-1] if "." in lower_name else "missing"
                    )
                },
            )

        if self.file_size_service.is_too_large(upload_file.file, max_size=max_size):
            raise FileTooLargeException()

        filepath = await self.file_size_service.save_file_to_disk(upload_file.file)
        filepath = Path(filepath)

        try:
            blob = bytes_extractor(filepath, TextMimeTypes.DOCX.value, sanitized_filename)
            text = self.text_extractor.extract_from_docx(filepath, sanitized_filename)
            checksum = self.file_size_service.get_file_checksum(filepath)
            return FileBaseWithContent(
                name=sanitized_filename,
                checksum=checksum,
                size=len(blob),
                file_type=FileType.DOCUMENT,
                mimetype=TextMimeTypes.DOCX.value,
                text=text,
                blob=blob,
            )
        finally:
            os.remove(filepath)

    async def to_domain(self, upload_file: UploadFile, max_size: int | None = None):
        if ImageMimeTypes.has_value(upload_file.content_type):
            return await self.image_to_domain(upload_file, max_size=max_size)
        elif AudioMimeTypes.has_value(upload_file.content_type):
            return await self.audio_to_domain(upload_file, max_size=max_size)

        return await self.text_to_domain(upload_file, max_size=max_size)
