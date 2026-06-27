from types import SimpleNamespace
from unittest.mock import MagicMock

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
    return MagicMock(file_type=FileType.TEXT)


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


def _assistant_with(max_input_tokens, n_attachments=1, prompt_text=None):
    model = SimpleNamespace(max_input_tokens=max_input_tokens, name="gpt-4o")
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


def test_validate_attachment_count_raises_above_cap(monkeypatch):
    monkeypatch.setattr(
        "intric.assistants.assistant.get_settings",
        lambda: _settings(attachment_max_files=3),
    )
    with pytest.raises(BadRequestException):
        Assistant.validate_attachment_count([_text_attachment() for _ in range(4)])


def test_validate_attachment_count_passes_at_cap(monkeypatch):
    monkeypatch.setattr(
        "intric.assistants.assistant.get_settings",
        lambda: _settings(attachment_max_files=3),
    )
    Assistant.validate_attachment_count([_text_attachment() for _ in range(3)])


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


def test_fit_rejects_when_over_ceiling(monkeypatch):
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
        AssistantService._validate_attachments_fit(
            _assistant_with(100, prompt_text="x")
        )


def test_fit_passes_when_within(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_tokens", lambda *a, **k: 5
    )
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **k: 80,
    )
    # used = 85 <= ceiling 90 -> ok
    AssistantService._validate_attachments_fit(_assistant_with(100, prompt_text="x"))


def test_fit_passes_at_exact_ceiling(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_tokens", lambda *a, **k: 0
    )
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **k: 90,
    )
    # used == ceiling is allowed (block only when strictly over)
    AssistantService._validate_attachments_fit(_assistant_with(100))


def test_fit_skipped_when_no_model(monkeypatch):
    _patch_reserve(monkeypatch, 10)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **k: 10**9,
    )
    assistant = SimpleNamespace(
        completion_model=None, attachments=[_text_attachment()], prompt=None
    )
    AssistantService._validate_attachments_fit(assistant)  # no raise


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
