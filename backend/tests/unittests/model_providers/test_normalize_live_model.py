"""Unit tests for the cross-provider /v1/models normalization helpers."""

from eneo.model_providers.domain.model_provider_service import (
    _auth_headers_for,
    _coerce_to_epoch,
    _extract_mode_hint,
    _normalize_endpoint_base,
    _normalize_live_model,
)


def test_normalizes_minimal_openai_compatible_shape() -> None:
    """Minimal OpenAI-compatible shape: just ``id`` and ``created`` epoch."""
    raw = {
        "id": "model-1",
        "object": "model",
        "created": 1715367049,
        "owned_by": "someone",
    }
    assert _normalize_live_model(raw) == {
        "id": "model-1",
        "display_name": "",
        "created_at": 1715367049.0,
        "mode_hint": None,
    }


def test_normalizes_shape_with_iso_created_and_display_name() -> None:
    """Some providers send ``display_name`` and an ISO ``created_at`` instead
    of an epoch ``created`` — the normalizer accepts both."""
    raw = {
        "type": "model",
        "id": "model-2",
        "display_name": "Model Two",
        "created_at": "2025-11-01T00:00:00Z",
    }
    out = _normalize_live_model(raw)
    assert out["id"] == "model-2"
    assert out["display_name"] == "Model Two"
    assert out["created_at"] > 0


def test_normalizes_shape_with_extra_fields() -> None:
    """Providers with richer responses (``name`` instead of ``display_name``,
    ``release_date`` alongside ``created``) work via the normalizer's fallback
    chains — no provider-specific code needed."""
    raw = {
        "id": "model-3",
        "name": "Model Three",
        "object": "model",
        "created": 1730000000,
        "release_date": "2025-09-15",
    }
    out = _normalize_live_model(raw)
    assert out["id"] == "model-3"
    assert out["display_name"] == "Model Three"  # falls back from `name`
    assert out["created_at"] == 1730000000.0  # `created` wins over release_date


def test_falls_back_to_release_date_when_no_created() -> None:
    raw = {"id": "x", "release_date": "2025-09-15"}
    assert _normalize_live_model(raw)["created_at"] > 0


def test_unknown_shape_still_works_with_just_id() -> None:
    raw = {"id": "mystery-model"}
    assert _normalize_live_model(raw) == {
        "id": "mystery-model",
        "display_name": "",
        "created_at": 0.0,
        "mode_hint": None,
    }


def test_anthropic_uses_x_api_key() -> None:
    headers = _auth_headers_for("anthropic", "sk-ant-test")
    assert headers == {
        "x-api-key": "sk-ant-test",
        "anthropic-version": "2023-06-01",
    }


def test_other_providers_use_bearer() -> None:
    assert _auth_headers_for("openai", "sk-test") == {"Authorization": "Bearer sk-test"}
    assert _auth_headers_for("vllm", "tok") == {"Authorization": "Bearer tok"}
    assert _auth_headers_for("berget", "tok") == {"Authorization": "Bearer tok"}


def test_endpoint_normalization_handles_v1_suffix() -> None:
    """Users may paste either ``https://api.example.com`` or ``…/v1`` and we
    must avoid producing ``/v1/v1/models`` either way."""
    assert (
        _normalize_endpoint_base("https://api.example.com") == "https://api.example.com"
    )
    assert (
        _normalize_endpoint_base("https://api.example.com/")
        == "https://api.example.com"
    )
    assert (
        _normalize_endpoint_base("https://api.example.com/v1")
        == "https://api.example.com"
    )
    assert (
        _normalize_endpoint_base("https://api.example.com/v1/")
        == "https://api.example.com"
    )
    # ``v1beta`` should NOT be stripped — only the exact ``/v1`` segment.
    assert (
        _normalize_endpoint_base("https://api.example.com/v1beta")
        == "https://api.example.com/v1beta"
    )
    # Path before /v1 is preserved.
    assert (
        _normalize_endpoint_base("https://gateway.example.com/proxy/v1")
        == "https://gateway.example.com/proxy"
    )


def test_mode_hint_from_explicit_model_type_embedding() -> None:
    raw = {"id": "x", "model_type": "embedding"}
    assert _extract_mode_hint(raw) == "embedding"


def test_mode_hint_from_text_with_embeddings_capability() -> None:
    """Some providers set ``model_type: "text"`` but flag embeddings via
    capabilities — we still classify as embedding."""
    raw = {
        "id": "x",
        "model_type": "text",
        "capabilities": {"embeddings": True},
    }
    assert _extract_mode_hint(raw) == "embedding"


def test_mode_hint_from_text_without_embeddings_is_completion() -> None:
    raw = {
        "id": "x",
        "model_type": "text",
        "capabilities": {"embeddings": False},
    }
    assert _extract_mode_hint(raw) == "completion"


def test_mode_hint_from_audio_model_type() -> None:
    assert _extract_mode_hint({"id": "x", "model_type": "audio"}) == "transcription"
    assert (
        _extract_mode_hint({"id": "x", "model_type": "transcription"})
        == "transcription"
    )


def test_mode_hint_returns_none_when_metadata_missing() -> None:
    """OpenAI/Anthropic don't expose model_type or capabilities on /v1/models —
    the hint extractor returns None and the caller falls back to name inference."""
    assert _extract_mode_hint({"id": "gpt-4o", "created": 1715367049}) is None
    assert _extract_mode_hint({"id": "claude", "display_name": "Claude"}) is None


def test_coerce_handles_epoch_int_iso_and_garbage() -> None:
    assert _coerce_to_epoch(1715367049) == 1715367049.0
    assert _coerce_to_epoch("2025-11-01T00:00:00Z") > 0
    assert _coerce_to_epoch(None) == 0.0
    assert _coerce_to_epoch("") == 0.0
    assert _coerce_to_epoch("not a date") == 0.0
