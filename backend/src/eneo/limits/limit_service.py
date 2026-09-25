from eneo.files.audio import AudioMimeTypes
from eneo.files.extensions import MIMETYPE_EXTENSIONS_MAPPER
from eneo.files.image import ImageMimeTypes
from eneo.files.text import TextMimeTypes
from eneo.limits.limit import AttachmentLimits, FormatLimit, InfoBlobLimits, Limits
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot


class LimitService:
    def __init__(self, upload_admission: UploadAdmissionSnapshot) -> None:
        self.upload_admission = upload_admission

    def _get_info_blob_limits(self) -> InfoBlobLimits:
        formats: list[FormatLimit] = []

        for item in TextMimeTypes.values():
            formats.append(
                FormatLimit(
                    mimetype=item,
                    size=self.upload_admission.knowledge_file_maximum_bytes,
                    extensions=MIMETYPE_EXTENSIONS_MAPPER[item],
                    vision=False,
                )
            )

        for item in AudioMimeTypes.values():
            formats.append(
                FormatLimit(
                    mimetype=item,
                    size=self.upload_admission.knowledge_audio_maximum_bytes,
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
                    size=self.upload_admission.session_file_maximum_bytes,
                    extensions=MIMETYPE_EXTENSIONS_MAPPER[item],
                    vision=False,
                )
            )

        for item in ImageMimeTypes.values():
            formats.append(
                FormatLimit(
                    mimetype=item,
                    size=self.upload_admission.session_image_maximum_bytes,
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
