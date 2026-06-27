from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from intric.assistants.assistant import Assistant
from intric.assistants.assistant_service import AssistantService
from intric.files.file_models import FileType
from intric.main.exceptions import BadRequestException


def _settings(**overrides):
    base = dict(
        attachment_max_files=15,
        attachment_context_budget_ratio=0.5,
        attachment_budget_enforced=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _text_attachment():
    return MagicMock(file_type=FileType.TEXT)


# --- count cap (domain, model-independent guardrail) ---


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


# --- token budget (service, model-dependent, gated by the enforcement flag) ---


def _assistant_with(max_input_tokens, n_attachments=1):
    model = SimpleNamespace(max_input_tokens=max_input_tokens, name="gpt-4o")
    return SimpleNamespace(
        completion_model=model,
        attachments=[_text_attachment() for _ in range(n_attachments)],
    )


def test_budget_rejects_when_projected_exceeds(monkeypatch):
    monkeypatch.setattr(
        "intric.assistants.assistant_service.get_settings",
        lambda: _settings(attachment_context_budget_ratio=0.5),
    )
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **kwargs: 100,
    )
    # budget = 0.5 * 100 = 50; projected 100 > 50 -> reject
    with pytest.raises(BadRequestException):
        AssistantService._validate_attachment_token_budget(_assistant_with(100))


def test_budget_passes_when_within(monkeypatch):
    monkeypatch.setattr(
        "intric.assistants.assistant_service.get_settings",
        lambda: _settings(attachment_context_budget_ratio=0.5),
    )
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **kwargs: 100,
    )
    # budget = 0.5 * 1000 = 500; projected 100 <= 500 -> ok
    AssistantService._validate_attachment_token_budget(_assistant_with(1000))


def test_budget_advisory_when_not_enforced(monkeypatch):
    monkeypatch.setattr(
        "intric.assistants.assistant_service.get_settings",
        lambda: _settings(attachment_budget_enforced=False),
    )
    calls = {"n": 0}

    def _counter(**kwargs):
        calls["n"] += 1
        return 10**9

    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens", _counter
    )
    # Returns early: no counting, no raise even though the count would be huge.
    AssistantService._validate_attachment_token_budget(_assistant_with(1))
    assert calls["n"] == 0


def test_budget_skipped_when_no_model(monkeypatch):
    monkeypatch.setattr(
        "intric.assistants.assistant_service.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **kwargs: 10**9,
    )
    assistant = SimpleNamespace(completion_model=None, attachments=[_text_attachment()])
    AssistantService._validate_attachment_token_budget(assistant)  # no raise
