from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.assistants.assistant import Assistant
from intric.assistants.assistant_service import AssistantService
from intric.files.attachment_budget import attachment_token_ceiling
from intric.files.file_models import FileType
from intric.main.exceptions import BadRequestException


def _settings(**overrides):
    base = dict(
        attachment_max_files=100,
        attachment_max_size_bytes=26214400,
        attachment_context_reserve_tokens=2000,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_reserve(monkeypatch, reserve):
    monkeypatch.setattr(
        "intric.files.attachment_budget.get_settings",
        lambda: _settings(attachment_context_reserve_tokens=reserve),
    )


def _text_attachment():
    return MagicMock(file_type=FileType.TEXT, mimetype="text/plain", size=1)


def _image_attachment():
    return MagicMock(file_type=FileType.IMAGE)


def _service(file_service=None):
    service = AssistantService(
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        user=MagicMock(),
        auth_service=MagicMock(),
        service_repo=AsyncMock(),
        step_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        factory=MagicMock(),
        prompt_service=AsyncMock(),
        file_service=file_service or AsyncMock(),
        assistant_template_service=AsyncMock(),
        session_service=AsyncMock(),
        actor_manager=MagicMock(),
        integration_knowledge_repo=AsyncMock(),
        completion_service=AsyncMock(),
        references_service=AsyncMock(),
        icon_repo=AsyncMock(),
        org_space_assistant_role_repo=AsyncMock(),
        help_assistant_assignment_history_repo=AsyncMock(),
    )
    return service


def _domain_assistant():
    return Assistant(
        id=None,
        user=MagicMock(),
        name=MagicMock(),
        space_id=MagicMock(),
        prompt=None,
        completion_model=None,
        completion_model_kwargs=ModelKwargs(),
        logging_enabled=False,
        websites=[],
        collections=[],
        attachments=[],
        published=False,
    )


def _assistant_with(max_input_tokens, n_attachments=1, prompt_text=None, vision=False):
    model = SimpleNamespace(
        max_input_tokens=max_input_tokens, name="gpt-4o", vision=vision
    )
    prompt = SimpleNamespace(text=prompt_text) if prompt_text is not None else None
    return SimpleNamespace(
        completion_model=model,
        attachments=[_text_attachment() for _ in range(n_attachments)],
        prompt=prompt,
    )


# --- fit ceiling (single source of truth) ---


def test_attachment_token_ceiling_subtracts_reserve(monkeypatch):
    _patch_reserve(monkeypatch, 2000)
    assert attachment_token_ceiling(100_000) == 98_000
    # Reserve larger than the window floors at 0 rather than going negative.
    _patch_reserve(monkeypatch, 200_000)
    assert attachment_token_ceiling(8_000) == 0


# --- count cap (domain, abuse guardrail) ---


def test_validate_attachments_raises_above_count_cap(monkeypatch):
    monkeypatch.setattr(
        "intric.assistants.assistant.get_settings",
        lambda: _settings(attachment_max_files=3),
    )
    with pytest.raises(BadRequestException):
        Assistant.validate_attachments([_text_attachment() for _ in range(4)])


def test_validate_attachments_passes_at_count_cap(monkeypatch):
    monkeypatch.setattr(
        "intric.assistants.assistant.get_settings",
        lambda: _settings(attachment_max_files=3),
    )
    Assistant.validate_attachments([_text_attachment() for _ in range(3)])


def test_validate_attachments_rejects_non_text_mimetype(monkeypatch):
    monkeypatch.setattr(
        "intric.assistants.assistant.get_settings",
        lambda: _settings(),
    )
    with pytest.raises(BadRequestException, match="text files"):
        Assistant.validate_attachments(
            [MagicMock(mimetype="image/png", size=1, file_type=FileType.IMAGE)]
        )


def test_validate_attachments_rejects_total_size_above_cap(monkeypatch):
    monkeypatch.setattr(
        "intric.assistants.assistant.get_settings",
        lambda: _settings(attachment_max_size_bytes=10),
    )
    with pytest.raises(BadRequestException, match="maximum total size"):
        Assistant.validate_attachments(
            [
                MagicMock(mimetype="text/plain", size=6, file_type=FileType.TEXT),
                MagicMock(mimetype="text/plain", size=5, file_type=FileType.TEXT),
            ]
        )


def test_update_enforces_count_cap_through_setter(monkeypatch):
    # The service update path routes attachments through Assistant.update -> the
    # setter, so the cap is enforced server-side on update, not just in the
    # static validator.
    monkeypatch.setattr(
        "intric.assistants.assistant.get_settings",
        lambda: _settings(attachment_max_files=2),
    )
    assistant = _domain_assistant()
    files = [
        MagicMock(mimetype="text/plain", size=1, file_type=FileType.TEXT)
        for _ in range(3)
    ]
    with pytest.raises(BadRequestException):
        assistant.update(attachments=files)


# --- context fit (service, always on): prompt + attachments must fit ---


@pytest.mark.asyncio
async def test_fit_rejects_when_over_ceiling(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_tokens", lambda *a, **k: 5
    )
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **k: 90,
    )
    # ceiling = 100 - 10 = 90; used = prompt 5 + attachments 90 = 95 > 90 -> reject
    with pytest.raises(BadRequestException):
        await _service()._validate_attachments_fit(
            _assistant_with(100, prompt_text="x")
        )


@pytest.mark.asyncio
async def test_fit_passes_when_within(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_tokens", lambda *a, **k: 5
    )
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **k: 80,
    )
    # used = 85 <= ceiling 90 -> ok
    await _service()._validate_attachments_fit(_assistant_with(100, prompt_text="x"))


@pytest.mark.asyncio
async def test_fit_passes_at_exact_ceiling(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_tokens", lambda *a, **k: 0
    )
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **k: 90,
    )
    # used == ceiling is allowed (block only when strictly over)
    await _service()._validate_attachments_fit(_assistant_with(100))


@pytest.mark.asyncio
async def test_fit_skipped_when_no_model(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **k: 10**9,
    )
    assistant = SimpleNamespace(
        completion_model=None, attachments=[_text_attachment()], prompt=None
    )
    await _service()._validate_attachments_fit(assistant)  # no raise


@pytest.mark.asyncio
async def test_fit_counts_derived_images_for_vision_model(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_tokens", lambda *a, **k: 0
    )

    def fake_count_attachment_tokens(*, text_files, image_files, model_name):
        return len(text_files) * 10 + len(image_files) * 90

    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        fake_count_attachment_tokens,
    )
    text_attachment = _text_attachment()
    derived_image = _image_attachment()
    file_service = AsyncMock()
    file_service.with_derived_images = AsyncMock(
        return_value=[text_attachment, derived_image]
    )

    # ceiling = 100 - 10 = 90; text 10 + derived image 90 = 100 -> reject
    with pytest.raises(BadRequestException):
        await _service(file_service)._validate_attachments_fit(
            _assistant_with(100, vision=True)
        )

    file_service.with_derived_images.assert_awaited_once()


@pytest.mark.asyncio
async def test_fit_does_not_count_derived_images_without_vision(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_tokens", lambda *a, **k: 0
    )

    def fake_count_attachment_tokens(*, text_files, image_files, model_name):
        return len(text_files) * 10 + len(image_files) * 90

    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        fake_count_attachment_tokens,
    )
    file_service = AsyncMock()
    file_service.with_derived_images = AsyncMock(
        return_value=[_text_attachment(), _image_attachment()]
    )

    await _service(file_service)._validate_attachments_fit(_assistant_with(100))

    file_service.with_derived_images.assert_not_awaited()


# --- assembler advertises the fit ceiling (None when no model) ---


def test_assembler_advertises_fit_ceiling(monkeypatch):
    from intric.assistants.api.assistant_assembler import AssistantAssembler

    monkeypatch.setattr(
        "intric.assistants.api.assistant_assembler.get_settings",
        lambda: _settings(attachment_max_files=100),
    )
    monkeypatch.setattr(
        "intric.files.attachment_budget.get_settings",
        lambda: _settings(attachment_context_reserve_tokens=2000),
    )
    assembler = AssistantAssembler(user=MagicMock(), prompt_assembler=MagicMock())

    restrictions = assembler._get_allowed_attachments(
        SimpleNamespace(max_input_tokens=100_000)
    )
    assert restrictions.limit.max_files == 100
    assert restrictions.limit.max_tokens == 98_000

    # No model selected -> ceiling is undefined.
    assert assembler._get_allowed_attachments(None).limit.max_tokens is None
