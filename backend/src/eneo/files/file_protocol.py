import asyncio
import contextlib
import os
from collections.abc import AsyncGenerator, AsyncIterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import UploadFile

from eneo.files.audio import AudioMimeTypes
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_size_service import FileSizeService
from eneo.files.image import ImageExtractor, ImageMimeTypes
from eneo.files.image_processing import (
    ProcessedImage,
    downscale_image,
    extract_images_from_office,
    extract_images_from_pdf,
)
from eneo.files.text import TextExtractor, TextMimeTypes
from eneo.main.config import get_settings
from eneo.main.exceptions import FileTooLargeException


def sanitize_filename(filename: str | None) -> str:
    """Sanitize filename to prevent path traversal attacks."""
    if not filename:
        return "unnamed"

    filename = filename.replace("\x00", "")
    filename = os.path.basename(filename).strip()

    return filename or "unnamed"


_FILE_STREAM_CHUNK_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class PendingFileContent:
    variant: FileContentVariant
    chunks: AsyncIterable[bytes]
    declared_media_type: str
    verified_media_type: str
    ordinal: int = 0
    page_number: int | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class PreparedFileUpload:
    name: str
    file_type: FileType
    display_media_type: str
    contents: tuple[PendingFileContent, ...]
    derivatives: tuple["PreparedFileUpload", ...] = ()


async def _path_chunks(filepath: Path) -> AsyncGenerator[bytes]:
    with filepath.open("rb") as source:
        while chunk := await asyncio.to_thread(source.read, _FILE_STREAM_CHUNK_BYTES):
            yield chunk


async def _bytes_chunks(payload: bytes) -> AsyncGenerator[bytes]:
    view = memoryview(payload)
    for start in range(0, len(view), _FILE_STREAM_CHUNK_BYTES):
        yield bytes(view[start : start + _FILE_STREAM_CHUNK_BYTES])


class FileProtocol:
    def __init__(
        self,
        file_size_service: FileSizeService,
        text_extractor: TextExtractor,
        image_extractor: ImageExtractor,
    ):
        super().__init__()
        self.file_size_service = file_size_service
        self.text_extractor = text_extractor
        self.image_extractor = image_extractor

    @asynccontextmanager
    async def prepare_upload(
        self,
        upload_file: UploadFile,
        *,
        max_size: int | None = None,
        limit_setting_name: str | None = None,
    ) -> AsyncGenerator[PreparedFileUpload]:
        """Classify one upload into exact and derived content variants.

        The exact source remains on the owner-only temporary path and is exposed
        as a bounded stream. Derived text and model inputs are separate variants;
        callers never need to infer whether a transformed value is the original.
        """
        content_type = (upload_file.content_type or "").split(";")[0].strip()
        if ImageMimeTypes.has_value(content_type):
            file_type = FileType.IMAGE
            if max_size is None:
                max_size = get_settings().upload_image_to_session_max_size
                limit_setting_name = (
                    limit_setting_name or "UPLOAD_IMAGE_TO_SESSION_MAX_SIZE"
                )
        elif AudioMimeTypes.has_value(content_type):
            file_type = FileType.AUDIO
            if max_size is None:
                max_size = get_settings().transcription_max_file_size
                limit_setting_name = limit_setting_name or "TRANSCRIPTION_MAX_FILE_SIZE"
        else:
            file_type = FileType.TEXT
            if max_size is None:
                max_size = get_settings().upload_file_to_session_max_size
                limit_setting_name = (
                    limit_setting_name or "UPLOAD_FILE_TO_SESSION_MAX_SIZE"
                )

        file_size = self.file_size_service.get_file_size(upload_file.file)
        if file_size > max_size:
            raise FileTooLargeException(
                file_size=file_size,
                max_size=max_size,
                setting_name=limit_setting_name,
            )

        filepath = Path(
            await self.file_size_service.save_file_to_disk(upload_file.file)
        )
        display_name = sanitize_filename(upload_file.filename)
        media_type = content_type or "application/octet-stream"

        try:
            original = PendingFileContent(
                variant=FileContentVariant.ORIGINAL,
                chunks=_path_chunks(filepath),
                declared_media_type=media_type,
                verified_media_type=media_type,
            )

            if file_type is FileType.IMAGE:
                image = self.image_extractor.extract(
                    filepath,
                    media_type,
                    upload_file.filename,
                )
                processed = downscale_image(image, media_type)
                model_input = PendingFileContent(
                    variant=FileContentVariant.MODEL_INPUT,
                    chunks=_bytes_chunks(processed.blob),
                    declared_media_type=processed.mimetype,
                    verified_media_type=processed.mimetype,
                )
                yield PreparedFileUpload(
                    name=display_name,
                    file_type=file_type,
                    display_media_type=media_type,
                    contents=(original, model_input),
                )
                return

            if file_type is FileType.AUDIO:
                yield PreparedFileUpload(
                    name=display_name,
                    file_type=file_type,
                    display_media_type=media_type,
                    contents=(original,),
                )
                return

            extracted_text = self.text_extractor.extract(
                filepath,
                media_type,
                upload_file.filename,
            ).encode("utf-8")
            extracted = PendingFileContent(
                variant=FileContentVariant.EXTRACTED_TEXT,
                chunks=_bytes_chunks(extracted_text),
                declared_media_type="text/plain",
                verified_media_type="text/plain",
            )

            derivatives: list[PreparedFileUpload] = []
            settings = get_settings()
            derivative_extractor: Callable[[Path], list[ProcessedImage]] | None = None
            if settings.attachment_image_extraction:
                if media_type == TextMimeTypes.PDF.value:

                    def extract_pdf(path: Path) -> list[ProcessedImage]:
                        return extract_images_from_pdf(
                            path,
                            max_images=settings.attachment_max_extracted_images,
                        )

                    derivative_extractor = extract_pdf
                elif media_type in (
                    TextMimeTypes.DOCX.value,
                    TextMimeTypes.PPTX.value,
                ):

                    def extract_office(path: Path) -> list[ProcessedImage]:
                        return extract_images_from_office(
                            path,
                            mimetype=media_type,
                            max_images=settings.attachment_max_extracted_images,
                        )

                    derivative_extractor = extract_office

            if derivative_extractor is not None:
                for index, image in enumerate(
                    derivative_extractor(filepath),
                    start=1,
                ):
                    label = (
                        f"page {image.page_number}"
                        if image.page_number is not None
                        else f"image {index}"
                    )
                    derivatives.append(
                        PreparedFileUpload(
                            name=f"{display_name} ({label})",
                            file_type=FileType.IMAGE,
                            display_media_type=image.mimetype,
                            contents=(
                                PendingFileContent(
                                    variant=FileContentVariant.DERIVED_PAGE,
                                    chunks=_bytes_chunks(image.blob),
                                    declared_media_type=image.mimetype,
                                    verified_media_type=image.mimetype,
                                    ordinal=index - 1,
                                    page_number=image.page_number,
                                ),
                            ),
                        )
                    )

            yield PreparedFileUpload(
                name=display_name,
                file_type=file_type,
                display_media_type=media_type,
                contents=(original, extracted),
                derivatives=tuple(derivatives),
            )
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.remove(filepath)
