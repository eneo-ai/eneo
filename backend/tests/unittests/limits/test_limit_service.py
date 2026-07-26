from eneo.files.audio import AudioMimeTypes
from eneo.files.image import ImageMimeTypes
from eneo.files.text import TextMimeTypes
from eneo.limits.limit_service import LimitService
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot


def test_limits_project_one_upload_admission_snapshot() -> None:
    upload_admission = UploadAdmissionSnapshot(
        policy_revision=9,
        session_storage_target=StorageKind.OBJECT_STORE,
        session_operator_ceiling_bytes=16,
        session_file_maximum_bytes=11,
        session_image_maximum_bytes=12,
        session_audio_maximum_bytes=13,
        knowledge_file_maximum_bytes=14,
        knowledge_audio_maximum_bytes=15,
    )

    limits = LimitService(upload_admission=upload_admission).get_limits()

    assert {item.size for item in limits.info_blobs.formats} == {14, 15}
    assert {
        item.size
        for item in limits.info_blobs.formats
        if item.mimetype in TextMimeTypes.values()
    } == {14}
    assert {
        item.size
        for item in limits.info_blobs.formats
        if item.mimetype in AudioMimeTypes.values()
    } == {15}
    assert {
        item.size
        for item in limits.attachments.formats
        if item.mimetype in TextMimeTypes.values()
    } == {11}
    assert {
        item.size
        for item in limits.attachments.formats
        if item.mimetype in ImageMimeTypes.values()
    } == {12}
