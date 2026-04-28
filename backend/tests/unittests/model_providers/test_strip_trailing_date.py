import pytest

from intric.model_providers.presentation.model_provider_router import (
    strip_trailing_date,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Anthropic dated snapshots
        ("claude-opus-4-7-20260416", "claude-opus-4-7"),
        ("claude-opus-4-6-20260205", "claude-opus-4-6"),
        ("claude-3-haiku-20240307", "claude-3-haiku"),
        # OpenAI dated snapshots
        ("gpt-4o-2024-08-06", "gpt-4o"),
        ("gpt-5.1-2025-11-13", "gpt-5.1"),
        ("o3-2025-04-16", "o3"),
        # Vertex @date format
        ("vertex_ai/claude-3-5-sonnet@20240620", "vertex_ai/claude-3-5-sonnet"),
        ("anthropic.claude-haiku-4-5@20251001", "anthropic.claude-haiku-4-5"),
    ],
)
def test_strips_trailing_date_suffix(name: str, expected: str) -> None:
    assert strip_trailing_date(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        # Plain alias names without dates
        "claude-opus-4-7",
        "gpt-4o",
        "gemini-2.0-flash",
        # Embedded short numeric suffix that is NOT a date (4-digit year+month, e.g. gpt-4-0314)
        "gpt-4-0314",
        # Bedrock version suffix
        "anthropic.claude-opus-4-6-v1",
        # Vertex @default (not a date)
        "vertex_ai/claude-opus-4-6@default",
        # 7-digit number (one short of YYYYMMDD)
        "some-model-1234567",
        # Date in the middle, not at end
        "gpt-4o-2024-08-06-fine-tuned",
    ],
)
def test_returns_none_when_no_trailing_date(name: str) -> None:
    assert strip_trailing_date(name) is None
