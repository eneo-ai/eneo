from unittest.mock import AsyncMock

import pytest

from eneo.files.audio import AudioMimeTypes
from eneo.files.image import ImageMimeTypes
from eneo.files.text import TextMimeTypes
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from eneo.limits.limit_service import LimitService
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot


def _upload_admission() -> UploadAdmissionSnapshot:
    return UploadAdmissionSnapshot(
        policy_revision=9,
        session_storage_target=StorageKind.OBJECT_STORE,
        session_operator_ceiling_bytes=16,
        session_file_maximum_bytes=11,
        session_image_maximum_bytes=12,
        session_audio_maximum_bytes=13,
        knowledge_file_maximum_bytes=14,
        knowledge_audio_maximum_bytes=15,
    )


@pytest.mark.anyio
async def test_limits_publish_effective_ai_builder_attachment_policy() -> None:
    settings_service = AsyncMock()
    settings_service.get_ai_builder_budget_policy.return_value = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=2_000,
        minimum_conversation_budget_tokens=4_000,
        max_attachments=37,
        max_message_chars=12_000,
    )

    limits = await LimitService(
        settings_service=settings_service,
        upload_admission=_upload_admission(),
    ).get_limits()

    assert limits.attachments.ai_builder_max_count == 37
    assert limits.attachments.ai_builder_max_message_chars == 12_000
    settings_service.get_ai_builder_budget_policy.assert_awaited_once_with()


@pytest.mark.anyio
async def test_limits_project_one_upload_admission_snapshot() -> None:
    settings_service = AsyncMock()
    settings_service.get_ai_builder_budget_policy.return_value = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=2_000,
        minimum_conversation_budget_tokens=4_000,
    )

    limits = await LimitService(
        settings_service=settings_service,
        upload_admission=_upload_admission(),
    ).get_limits()

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
