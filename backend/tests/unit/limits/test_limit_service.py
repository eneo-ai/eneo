"""Chat attachment limits advertise every format the ask path can read."""

from eneo.files.audio import AudioMimeTypes
from eneo.limits.limit_service import LimitService
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot


def test_attachments_accept_audio_at_the_session_audio_limit() -> None:
    upload_admission = UploadAdmissionSnapshot(
        policy_revision=1,
        new_write_storage_target=StorageKind.OBJECT_STORE,
        session_file_maximum_bytes=11,
        session_image_maximum_bytes=12,
        session_audio_maximum_bytes=13,
        knowledge_file_maximum_bytes=14,
        knowledge_audio_maximum_bytes=15,
    )

    limits = LimitService(upload_admission=upload_admission).get_limits()

    audio = [
        item
        for item in limits.attachments.formats
        if item.mimetype in AudioMimeTypes.values()
    ]
    assert {item.mimetype for item in audio} == set(AudioMimeTypes.values())
    assert {item.size for item in audio} == {13}
    # The transcript is text: no vision needed to attach audio.
    assert not any(item.vision for item in audio)
