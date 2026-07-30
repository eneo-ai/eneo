from typing import TYPE_CHECKING

from eneo.files.extensions import MIMETYPE_EXTENSIONS_MAPPER
from eneo.files.mime_support import (
    supported_audio_mimes,
    supported_image_mimes,
    supported_text_mimes,
)
from eneo.limits.limit import AttachmentLimits, FormatLimit, InfoBlobLimits, Limits
from eneo.main.config import get_settings

if TYPE_CHECKING:
    from eneo.settings.setting_service import SettingService


class LimitService:
    def __init__(self, *, settings_service: "SettingService") -> None:
        self.settings_service = settings_service

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

    async def _get_attachment_limits(self) -> AttachmentLimits:
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

        builder_policy = await self.settings_service.get_ai_builder_budget_policy()
        return AttachmentLimits(
            formats=formats,
            ai_builder_max_count=builder_policy.max_attachments,
            ai_builder_max_message_chars=builder_policy.max_message_chars,
        )

    async def get_limits(self) -> Limits:
        return Limits(
            info_blobs=self._get_info_blob_limits(),
            attachments=await self._get_attachment_limits(),
        )
