from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.assistants.assistant import Assistant
from intric.assistants.assistant_service import AssistantService
from intric.files.attachment_budget import compute_attachment_token_budget
from intric.files.file_models import FileType
from intric.main.exceptions import BadRequestException


def _settings(**overrides):
    base = dict(
        attachment_max_files=15,
        attachment_context_budget_ratio=0.5,
        attachment_budget_enforced=True,
        attachment_max_size_bytes=26214400,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_budget_settings(monkeypatch, **overrides):
    """The budget number and the enforcement flag are read from two modules
    (the helper owns the ratio, the service owns the flag); patch both so a test
    never silently falls back to real defaults."""
    settings = _settings(**overrides)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.get_settings", lambda: settings
    )
    monkeypatch.setattr("intric.files.attachment_budget.get_settings", lambda: settings)


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


# --- shared budget helper (single source of truth) ---


def test_compute_attachment_token_budget_scales_with_model(monkeypatch):
    monkeypatch.setattr(
        "intric.files.attachment_budget.get_settings",
        lambda: _settings(attachment_context_budget_ratio=0.25),
    )
    assert compute_attachment_token_budget(100_000) == 25_000
    assert compute_attachment_token_budget(8_000) == 2_000


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


# --- token budget (service, model-dependent, gated by the enforcement flag) ---


def _assistant_with(max_input_tokens, n_attachments=1):
    model = SimpleNamespace(max_input_tokens=max_input_tokens, name="gpt-4o")
    return SimpleNamespace(
        completion_model=model,
        attachments=[_text_attachment() for _ in range(n_attachments)],
    )


def test_budget_rejects_when_projected_exceeds(monkeypatch):
    _patch_budget_settings(monkeypatch, attachment_context_budget_ratio=0.5)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **kwargs: 100,
    )
    # budget = 0.5 * 100 = 50; projected 100 > 50 -> reject
    with pytest.raises(BadRequestException):
        AssistantService._validate_attachment_token_budget(_assistant_with(100))


def test_budget_passes_when_within(monkeypatch):
    _patch_budget_settings(monkeypatch, attachment_context_budget_ratio=0.5)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **kwargs: 100,
    )
    # budget = 0.5 * 1000 = 500; projected 100 <= 500 -> ok
    AssistantService._validate_attachment_token_budget(_assistant_with(1000))


def test_budget_passes_at_exact_boundary(monkeypatch):
    _patch_budget_settings(monkeypatch, attachment_context_budget_ratio=0.5)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **kwargs: 50,
    )
    # budget = 50; projected == budget is allowed (block only when strictly over)
    AssistantService._validate_attachment_token_budget(_assistant_with(100))


def test_budget_rejects_one_token_over(monkeypatch):
    _patch_budget_settings(monkeypatch, attachment_context_budget_ratio=0.5)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **kwargs: 51,
    )
    # budget = 50; projected 51 > 50 -> reject
    with pytest.raises(BadRequestException):
        AssistantService._validate_attachment_token_budget(_assistant_with(100))


def test_budget_advisory_when_not_enforced(monkeypatch):
    _patch_budget_settings(monkeypatch, attachment_budget_enforced=False)
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
    _patch_budget_settings(monkeypatch)
    monkeypatch.setattr(
        "intric.assistants.assistant_service.count_attachment_tokens",
        lambda **kwargs: 10**9,
    )
    assistant = SimpleNamespace(completion_model=None, attachments=[_text_attachment()])
    AssistantService._validate_attachment_token_budget(assistant)  # no raise


# --- assembler advertises the budget (None when no model) ---


def test_assembler_advertises_token_budget(monkeypatch):
    from intric.assistants.api.assistant_assembler import AssistantAssembler

    monkeypatch.setattr(
        "intric.assistants.api.assistant_assembler.get_settings",
        lambda: _settings(attachment_max_files=15),
    )
    monkeypatch.setattr(
        "intric.files.attachment_budget.get_settings",
        lambda: _settings(attachment_context_budget_ratio=0.5),
    )
    assembler = AssistantAssembler(user=MagicMock(), prompt_assembler=MagicMock())

    restrictions = assembler._get_allowed_attachments(
        SimpleNamespace(max_input_tokens=100_000)
    )
    assert restrictions.limit.max_files == 15
    assert restrictions.limit.max_tokens == 50_000

    # No model selected -> budget is undefined.
    assert assembler._get_allowed_attachments(None).limit.max_tokens is None
