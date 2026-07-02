from eneo.files.extensions import MIMETYPE_EXTENSIONS_MAPPER
from eneo.files.mime_support import (
    supported_audio_mimes,
    supported_image_mimes,
    supported_text_mimes,
)
from eneo.limits.limit import AttachmentLimits, FormatLimit, InfoBlobLimits, Limits
from eneo.main.config import get_settings


class LimitService:
    def _get_info_blob_limits(self) -> InfoBlobLimits:
        formats: list[FormatLimit] = []

        for item in supported_text_mimes():
            formats.append(
                FormatLimit(
                    mimetype=item,
                    size=get_settings().upload_max_file_size,
                    extensions=MIMETYPE_EXTENSIONS_MAPPER[item],
                    vision=False,
                )
            )

        for item in supported_audio_mimes():
            formats.append(
                FormatLimit(
                    mimetype=item,
                    size=get_settings().transcription_max_file_size,
                    extensions=MIMETYPE_EXTENSIONS_MAPPER[item],
                    vision=False,
                )
            )

        return InfoBlobLimits(formats=formats)

    def _get_attachment_limits(self) -> AttachmentLimits:
        formats: list[FormatLimit] = []

        for item in supported_text_mimes():
            formats.append(
                FormatLimit(
                    mimetype=item,
                    size=get_settings().upload_file_to_session_max_size,
                    extensions=MIMETYPE_EXTENSIONS_MAPPER[item],
                    vision=False,
                )
            )

        for item in supported_image_mimes():
            formats.append(
                FormatLimit(
                    mimetype=item,
                    size=get_settings().upload_image_to_session_max_size,
                    extensions=MIMETYPE_EXTENSIONS_MAPPER[item],
                    vision=True,
                )
            )

        return AttachmentLimits(
            formats=formats,
        )

    def get_limits(self) -> Limits:
        return Limits(
            info_blobs=self._get_info_blob_limits(),
            attachments=self._get_attachment_limits(),
        )
