"""Tests for create-body scope mismatch validation (Plan 1D).

Covers:
- POST /assistants/ with space-scoped key: space_id mismatch → 403
- POST /assistants/ with matching space_id → passes
- POST /assistants/ with no space_id in body → passes (no constraint)
- Tenant-scoped key → no scope check
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.datastructures import State

from intric.authentication.auth_dependencies import ScopeFilter, get_scope_filter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    scope_type: str | None = None,
    scope_id: UUID | None = None,
    *,
    scope_enforcement_enabled: bool | None = None,
) -> SimpleNamespace:
    """Build a minimal request with scope state (as set by auth middleware)."""
    state = State()
    if scope_enforcement_enabled is not None:
        state.scope_enforcement_enabled = scope_enforcement_enabled
    if scope_type is not None:
        state.api_key_scope_type = scope_type
        state.api_key_scope_id = scope_id
    return SimpleNamespace(state=state)


def _simulate_create_assistant_scope_check(
    scope_filter: ScopeFilter,
    body_space_id: UUID | None,
) -> None:
    """Reproduce the exact scope validation logic from assistant_router.create_assistant."""
    if scope_filter.space_id is not None and body_space_id is not None:
        if scope_filter.space_id != body_space_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "insufficient_scope",
                    "message": (
                        f"API key is scoped to space '{scope_filter.space_id}'. "
                        f"Cannot create assistant in space '{body_space_id}'."
                    ),
                },
            )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateAssistantScopeValidation:
    """POST /assistants/ body-scope mismatch tests."""

    def test_space_scoped_key_create_assistant_wrong_space_id_returns_403(self):
        """Space-scoped key + body space_id != key scope → 403 insufficient_scope."""
        key_space = uuid4()
        body_space = uuid4()
        request = _make_request(scope_type="space", scope_id=key_space)
        scope_filter = get_scope_filter(request)

        with pytest.raises(HTTPException) as exc_info:
            _simulate_create_assistant_scope_check(scope_filter, body_space)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "insufficient_scope"
        assert str(key_space) in exc_info.value.detail["message"]
        assert str(body_space) in exc_info.value.detail["message"]

    def test_space_scoped_key_create_assistant_matching_space_id_passes(self):
        """Space-scoped key + body space_id == key scope → pass (no exception)."""
        space_id = uuid4()
        request = _make_request(scope_type="space", scope_id=space_id)
        scope_filter = get_scope_filter(request)

        # Should not raise
        _simulate_create_assistant_scope_check(scope_filter, space_id)

    def test_space_scoped_key_create_assistant_no_body_space_id_passes(self):
        """Space-scoped key + no space_id in body → pass (no constraint to check)."""
        key_space = uuid4()
        request = _make_request(scope_type="space", scope_id=key_space)
        scope_filter = get_scope_filter(request)

        # body_space_id=None means the check is skipped
        _simulate_create_assistant_scope_check(scope_filter, None)

    def test_tenant_scoped_key_create_assistant_any_space_passes(self):
        """Tenant-scoped key → no scope constraint, any space_id passes."""
        request = _make_request(scope_type="tenant", scope_id=uuid4())
        scope_filter = get_scope_filter(request)

        assert scope_filter.space_id is None
        # Any space_id in body should pass
        _simulate_create_assistant_scope_check(scope_filter, uuid4())

    def test_bearer_auth_no_scope_filter_passes(self):
        """Bearer auth (no API key scope) → no constraint."""
        request = _make_request()  # no scope state
        scope_filter = get_scope_filter(request)

        assert scope_filter.scope_type is None
        assert scope_filter.space_id is None
        _simulate_create_assistant_scope_check(scope_filter, uuid4())

    def test_assistant_scoped_key_has_no_space_filter(self):
        """Assistant-scoped key → space_id is None, no space constraint on create."""
        assistant_id = uuid4()
        request = _make_request(scope_type="assistant", scope_id=assistant_id)
        scope_filter = get_scope_filter(request)

        assert scope_filter.space_id is None
        _simulate_create_assistant_scope_check(scope_filter, uuid4())

    def test_scope_enforcement_off_create_mismatch_not_blocked(self):
        """Kill-switch OFF: space mismatch check should not trigger from scope filter."""
        request = _make_request(
            scope_type="space",
            scope_id=uuid4(),
            scope_enforcement_enabled=False,
        )
        scope_filter = get_scope_filter(request)

        assert scope_filter.scope_type is None
        assert scope_filter.space_id is None
        _simulate_create_assistant_scope_check(scope_filter, uuid4())


class TestScopeFilterExtraction:
    """Verify get_scope_filter correctly extracts scope from request state."""

    def test_space_scope_extracts_space_id(self):
        space_id = uuid4()
        request = _make_request(scope_type="space", scope_id=space_id)
        sf = get_scope_filter(request)
        assert sf.scope_type == "space"
        assert sf.space_id == space_id
        assert sf.assistant_id is None

    def test_assistant_scope_extracts_assistant_id(self):
        assistant_id = uuid4()
        request = _make_request(scope_type="assistant", scope_id=assistant_id)
        sf = get_scope_filter(request)
        assert sf.scope_type == "assistant"
        assert sf.assistant_id == assistant_id
        assert sf.space_id is None

    def test_tenant_scope_has_no_ids(self):
        request = _make_request(scope_type="tenant", scope_id=uuid4())
        sf = get_scope_filter(request)
        assert sf.scope_type == "tenant"
        assert sf.space_id is None
        assert sf.assistant_id is None

    def test_no_scope_returns_empty(self):
        request = _make_request()
        sf = get_scope_filter(request)
        assert sf.scope_type is None
        assert sf.space_id is None
        assert sf.assistant_id is None

    def test_scope_enforcement_disabled_returns_empty_even_with_scope_state(self):
        space_id = uuid4()
        request = _make_request(
            scope_type="space",
            scope_id=space_id,
            scope_enforcement_enabled=False,
        )
        sf = get_scope_filter(request)
        assert sf.scope_type is None
        assert sf.space_id is None
        assert sf.assistant_id is None

    def test_scope_enforcement_enabled_preserves_scope_extraction(self):
        space_id = uuid4()
        request = _make_request(
            scope_type="space",
            scope_id=space_id,
            scope_enforcement_enabled=True,
        )
        sf = get_scope_filter(request)
        assert sf.scope_type == "space"
        assert sf.space_id == space_id
        assert sf.assistant_id is None
