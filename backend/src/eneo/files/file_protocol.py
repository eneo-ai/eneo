import contextlib
import hashlib
import os
from pathlib import Path
from typing import Callable

from fastapi import UploadFile

from eneo.files.audio import AudioMimeTypes
from eneo.files.file_models import FileBaseWithContent, FileType
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
        super().__init__()
        self.file_size_service = file_size_service
        self.text_extractor = text_extractor
        self.image_extractor = image_extractor

    async def _get_content(
        self,
        upload_file: UploadFile,
        file_type: FileType,
        max_size: int,
        extractor: Callable[[Path, str, str | None], str | bytes],
        limit_setting_name: str | None = None,
        on_disk_hook: Callable[[Path], None] | None = None,
    ):
        file_size = self.file_size_service.get_file_size(upload_file.file)
        if file_size > max_size:
            raise FileTooLargeException(
                file_size=file_size,
                max_size=max_size,
                setting_name=limit_setting_name,
            )

        # save_file_to_disk closes the upload stream — this temp file is the
        # only window where the content is readable from disk.
        filepath = await self.file_size_service.save_file_to_disk(upload_file.file)
        filepath = Path(filepath)

        try:
            # content_type can be None for uploads without Content-Type header
            content_type: str = upload_file.content_type or ""
            content = extractor(filepath, content_type, upload_file.filename)
            checksum = self.file_size_service.get_file_checksum(filepath)

            if isinstance(content, str):
                size = len(content.encode("utf-8"))
            else:
                size = len(content)

            if on_disk_hook is not None:
                on_disk_hook(filepath)

            return self._create_file_base(
                upload_file, file_type, content, checksum, size
            )
        finally:
            with contextlib.suppress(FileNotFoundError):
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

        if file_type == FileType.TEXT:
            return FileBaseWithContent(
                name=sanitized_filename,
                checksum=checksum,
                size=size,
                file_type=file_type,
                mimetype=upload_file.content_type,
                text=content if isinstance(content, str) else None,
            )
        else:
            return FileBaseWithContent(
                name=sanitized_filename,
                checksum=checksum,
                size=size,
                file_type=file_type,
                mimetype=upload_file.content_type,
                blob=content if isinstance(content, bytes) else None,
            )

    async def text_to_domain(
        self,
        upload_file: UploadFile,
        max_size: int | None = None,
        limit_setting_name: str | None = None,
        on_disk_hook: Callable[[Path], None] | None = None,
    ):
        if max_size is None:
            max_size = get_settings().upload_file_to_session_max_size
            if limit_setting_name is None:
                limit_setting_name = "UPLOAD_FILE_TO_SESSION_MAX_SIZE"

        return await self._get_content(
            upload_file,
            file_type=FileType.TEXT,
            max_size=max_size,
            extractor=self.text_extractor.extract,
            limit_setting_name=limit_setting_name,
            on_disk_hook=on_disk_hook,
        )

    async def image_to_domain(
        self,
        upload_file: UploadFile,
        max_size: int | None = None,
        limit_setting_name: str | None = None,
    ):
        if max_size is None:
            max_size = get_settings().upload_image_to_session_max_size
            if limit_setting_name is None:
                limit_setting_name = "UPLOAD_IMAGE_TO_SESSION_MAX_SIZE"

        file = await self._get_content(
            upload_file,
            file_type=FileType.IMAGE,
            max_size=max_size,
            extractor=self.image_extractor.extract,
            limit_setting_name=limit_setting_name,
        )

        # Vision images are base64-encoded into every model request (and
        # replayed for the rest of the session), so store them downscaled.
        if file.blob is not None:
            processed = downscale_image(file.blob, file.mimetype)
            file.blob = processed.blob
            file.mimetype = processed.mimetype
            file.size = len(processed.blob)
            file.checksum = hashlib.sha256(processed.blob).hexdigest()

        return file

    async def to_domain_with_derivatives(
        self,
        upload_file: UploadFile,
        max_size: int | None = None,
        limit_setting_name: str | None = None,
    ) -> tuple[FileBaseWithContent, list[FileBaseWithContent]]:
        """Like to_domain, but document uploads (PDF/DOCX/PPTX) also yield
        their visual content as derived image files.

        Image extraction is best-effort: it runs inside the upload's temp-file
        window (the stream is closed afterwards) and never breaks the upload.
        """
        settings = get_settings()
        content_type = (upload_file.content_type or "").split(";")[0].strip()

        extractor: Callable[[Path], list[ProcessedImage]] | None = None
        if settings.attachment_image_extraction:
            if content_type == TextMimeTypes.PDF.value:

                def _extract_pdf(filepath: Path) -> list[ProcessedImage]:
                    return extract_images_from_pdf(
                        filepath,
                        max_images=settings.attachment_max_extracted_images,
                    )

                extractor = _extract_pdf
            elif content_type in (
                TextMimeTypes.DOCX.value,
                TextMimeTypes.PPTX.value,
            ):

                def _extract_office(filepath: Path) -> list[ProcessedImage]:
                    return extract_images_from_office(
                        filepath,
                        mimetype=content_type,
                        max_images=settings.attachment_max_extracted_images,
                    )

                extractor = _extract_office

        if extractor is None:
            return (
                await self.to_domain(
                    upload_file,
                    max_size=max_size,
                    limit_setting_name=limit_setting_name,
                ),
                [],
            )

        extracted: list[ProcessedImage] = []
        extract = extractor

        def collect_images(filepath: Path) -> None:
            extracted.extend(extract(filepath))

        file = await self.text_to_domain(
            upload_file,
            max_size=max_size,
            limit_setting_name=limit_setting_name,
            on_disk_hook=collect_images,
        )

        derivatives: list[FileBaseWithContent] = []
        for index, image in enumerate(extracted, start=1):
            label = (
                f"page {image.page_number}"
                if image.page_number is not None
                else f"image {index}"
            )
            derivatives.append(
                FileBaseWithContent(
                    name=f"{file.name} ({label})",
                    checksum=hashlib.sha256(image.blob).hexdigest(),
                    size=len(image.blob),
                    file_type=FileType.IMAGE,
                    mimetype=image.mimetype,
                    blob=image.blob,
                )
            )
        return file, derivatives

    async def audio_to_domain(
        self,
        upload_file: UploadFile,
        max_size: int | None = None,
        limit_setting_name: str | None = None,
    ):
        if max_size is None:
            max_size = get_settings().transcription_max_file_size
            if limit_setting_name is None:
                limit_setting_name = "TRANSCRIPTION_MAX_FILE_SIZE"

        return await self._get_content(
            upload_file,
            file_type=FileType.AUDIO,
            max_size=max_size,
            extractor=bytes_extractor,
            limit_setting_name=limit_setting_name,
        )

    async def to_domain(
        self,
        upload_file: UploadFile,
        max_size: int | None = None,
        limit_setting_name: str | None = None,
    ):
        content_type = upload_file.content_type or ""
        if ImageMimeTypes.has_value(content_type):
            return await self.image_to_domain(
                upload_file,
                max_size=max_size,
                limit_setting_name=limit_setting_name,
            )
        elif AudioMimeTypes.has_value(content_type):
            return await self.audio_to_domain(
                upload_file,
                max_size=max_size,
                limit_setting_name=limit_setting_name,
            )

        return await self.text_to_domain(
            upload_file,
            max_size=max_size,
            limit_setting_name=limit_setting_name,
        )
