import os
from pathlib import Path
from typing import Callable

from fastapi import UploadFile

from intric.files.audio import AudioMimeTypes
from intric.files.file_models import FileBaseWithContent, FileType
from intric.files.file_size_service import FileSizeService
from intric.files.image import ImageExtractor, ImageMimeTypes
from intric.files.text import TextExtractor
from intric.main.config import get_settings
from intric.main.exceptions import FileTooLargeException


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

    async def to_domain(self, upload_file: UploadFile, max_size: int | None = None):
        if ImageMimeTypes.has_value(upload_file.content_type):
            return await self.image_to_domain(upload_file, max_size=max_size)
        elif AudioMimeTypes.has_value(upload_file.content_type):
            return await self.audio_to_domain(upload_file, max_size=max_size)

        return await self.text_to_domain(upload_file, max_size=max_size)
