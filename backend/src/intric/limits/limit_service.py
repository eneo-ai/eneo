from intric.files.audio import AudioMimeTypes
from intric.files.extensions import MIMETYPE_EXTENSIONS_MAPPER
from intric.files.image import ImageMimeTypes
from intric.files.text import TextMimeTypes
from intric.limits.limit import AttachmentLimits, FormatLimit, InfoBlobLimits, Limits
from intric.main.config import get_settings


class LimitService:
    def _get_info_blob_limits(self) -> InfoBlobLimits:
        formats: list[FormatLimit] = []

        for item in TextMimeTypes.values():
            formats.append(
                FormatLimit(
                    mimetype=item,
                    size=get_settings().upload_max_file_size,
                    extensions=MIMETYPE_EXTENSIONS_MAPPER[item],
                    vision=False,
                )
            )

        for item in AudioMimeTypes.values():
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

        for item in TextMimeTypes.values():
            formats.append(
                FormatLimit(
                    mimetype=item,
                    size=get_settings().upload_file_to_session_max_size,
                    extensions=MIMETYPE_EXTENSIONS_MAPPER[item],
                    vision=False,
                )
            )

        for item in ImageMimeTypes.values():
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
