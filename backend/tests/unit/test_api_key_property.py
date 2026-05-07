"""Property-style tests for API-key v2 permission resolution.

Two invariants, enforced over a large sample space without hypothesis:

1. **Oracle invariant** — a pure-Python re-implementation of
   ``check_resource_permission`` must produce the same verdict (allow / deny)
   as the live implementation for every well-formed input. Any drift between
   the oracle and the implementation means one of them is wrong — and that is
   exactly what we want to surface.

2. **Fail-closed invariant** — for malformed, garbage, or adversarial
   ``resource_permissions`` payloads, the implementation must either:
   (a) raise :class:`ApiKeyValidationError` (explicit deny), or
   (b) treat the unknown/missing slot as ``none`` (implicit deny) so a
       ``write`` request is never permitted on a missing granularity.

The exhaustive well-formed space is 4 × 4⁴ = 1024 combinations of
``(basic_permission, resource_permissions, required)`` — small enough to
enumerate. The adversarial space is sampled via a deterministic PRNG seeded
per-test so failures are reproducible.
"""

from __future__ import annotations

import itertools
import random
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from intric.authentication.api_key_resolver import (
    ApiKeyValidationError,
    check_resource_permission,
)
from intric.authentication.auth_models import (
    PERMISSION_LEVEL_ORDER,
    ApiKeyPermission,
)

# ---------------------------------------------------------------------------
# Oracle — independent re-implementation of check_resource_permission
# ---------------------------------------------------------------------------


RESOURCE_PERMISSION_FIELDS: tuple[str, ...] = (
    "assistants",
    "apps",
    "spaces",
    "knowledge",
)
LEVELS: tuple[str, ...] = ("none", "read", "write", "admin")
BASIC_PERMISSIONS: tuple[str, ...] = ("read", "write", "admin")


def oracle_check(
    *,
    basic_permission: str,
    resource_permissions: dict[str, str] | None,
    resource_type: str,
    required: str,
    flag_enabled: bool,
) -> str:
    """Return 'allow' or 'deny' for the given inputs.

    Kept deliberately simple (≈30 lines) so it is easy to read. Deliberately
    *not* importing any helper from the implementation — if the implementation
    drifts, the oracle must not drift with it.
    """
    if not flag_enabled:
        return "allow"

    # No fine-grained: basic permission is the ceiling.
    if resource_permissions is None:
        key_level = PERMISSION_LEVEL_ORDER.get(basic_permission, 0)
        required_level = PERMISSION_LEVEL_ORDER.get(required, 0)
        return "allow" if key_level >= required_level else "deny"

    # Unknown resource_type → granted_level 0 → deny anything above none.
    granted_value = resource_permissions.get(resource_type)
    if granted_value not in LEVELS:
        granted_level = 0
    else:
        granted_level = PERMISSION_LEVEL_ORDER.get(granted_value, 0)

    required_level = PERMISSION_LEVEL_ORDER.get(required, 0)
    return "allow" if granted_level >= required_level else "deny"


def _make_key(
    *,
    basic_permission: str,
    resource_permissions: Any,
) -> SimpleNamespace:
    """Minimal stand-in for ``ApiKeyV2InDB``.

    ``check_resource_permission`` only reads ``.permission`` and
    ``.resource_permissions`` off the key object, so a namespace is enough
    and bypasses Pydantic validation on the fields we want to adversarially
    set to garbage.
    """
    perm = (
        basic_permission.value
        if isinstance(basic_permission, ApiKeyPermission)
        else basic_permission
    )
    return SimpleNamespace(
        permission=perm,
        resource_permissions=resource_permissions,
    )


def _run_impl(
    *,
    basic_permission: str,
    resource_permissions: Any,
    resource_type: str,
    required: str,
    flag_enabled: bool = True,
) -> str:
    """Invoke the real implementation and translate to 'allow'/'deny'."""
    key = _make_key(
        basic_permission=basic_permission,
        resource_permissions=resource_permissions,
    )
    with patch("intric.authentication.api_key_resolver.get_settings") as mock_settings:
        mock_settings.return_value.api_key_enforce_resource_permissions = flag_enabled
        try:
            check_resource_permission(key, resource_type, required)
        except ApiKeyValidationError:
            return "deny"
    return "allow"


# ---------------------------------------------------------------------------
# Invariant 1: Oracle agrees with implementation on the well-formed space
# ---------------------------------------------------------------------------


def _well_formed_rp_dicts():
    """Enumerate every (4⁴ = 256) well-formed resource_permissions dict."""
    for combo in itertools.product(LEVELS, repeat=len(RESOURCE_PERMISSION_FIELDS)):
        yield dict(zip(RESOURCE_PERMISSION_FIELDS, combo))


@pytest.mark.parametrize("flag_enabled", [True, False])
@pytest.mark.parametrize(
    "required", LEVELS[1:]
)  # skip 'none' — no endpoint requires none
@pytest.mark.parametrize("resource_type", RESOURCE_PERMISSION_FIELDS)
def test_oracle_agrees_with_implementation_when_no_resource_permissions(
    flag_enabled: bool, required: str, resource_type: str
):
    """For every basic permission × (flag_enabled, required, resource_type),
    when ``resource_permissions=None`` the oracle and implementation agree."""
    for basic in BASIC_PERMISSIONS:
        expected = oracle_check(
            basic_permission=basic,
            resource_permissions=None,
            resource_type=resource_type,
            required=required,
            flag_enabled=flag_enabled,
        )
        actual = _run_impl(
            basic_permission=basic,
            resource_permissions=None,
            resource_type=resource_type,
            required=required,
            flag_enabled=flag_enabled,
        )
        assert actual == expected, (
            f"Drift on basic={basic!r}, resource={resource_type!r}, "
            f"required={required!r}, flag={flag_enabled!r}: "
            f"oracle={expected}, impl={actual}"
        )


@pytest.mark.parametrize("required", LEVELS[1:])
@pytest.mark.parametrize("resource_type", RESOURCE_PERMISSION_FIELDS)
def test_oracle_agrees_with_implementation_on_well_formed_resource_permissions(
    required: str, resource_type: str
):
    """Enumerate all 256 well-formed resource_permissions dicts; oracle and
    implementation must agree for every (rp, resource_type, required) triple.

    Basic permission fixed to ``admin`` so the basic-permission ceiling is not
    the decider — we are isolating the fine-grained code path.
    """
    drift: list[str] = []
    for rp in _well_formed_rp_dicts():
        expected = oracle_check(
            basic_permission="admin",
            resource_permissions=rp,
            resource_type=resource_type,
            required=required,
            flag_enabled=True,
        )
        actual = _run_impl(
            basic_permission="admin",
            resource_permissions=rp,
            resource_type=resource_type,
            required=required,
            flag_enabled=True,
        )
        if actual != expected:
            drift.append(
                f"rp={rp}, resource={resource_type}, required={required}: "
                f"oracle={expected} impl={actual}"
            )
    assert not drift, "Oracle/implementation drift:\n  - " + "\n  - ".join(drift)


# ---------------------------------------------------------------------------
# Invariant 2: Malformed / adversarial inputs fail closed
# ---------------------------------------------------------------------------


# Hand-crafted adversarial payloads. Every one of these must never allow a
# request that requires ``write`` or higher on any known resource_type.
_MALFORMED_PAYLOADS: list[Any] = [
    {},  # empty dict — all resources implicitly 'none'
    {"assistants": "super_admin"},  # unknown level string
    {"assistants": 999},  # wrong type — int
    {"assistants": True},  # wrong type — bool
    {"assistants": None},  # explicit None
    {"assistants": ["admin"]},  # wrong type — list
    {"assistants": {"nested": "admin"}},  # wrong type — nested dict
    {"unknown_resource": "admin"},  # unknown resource_type key only
    {"assistants": "ADMIN"},  # wrong case
    {"assistants": "admin", "extra": "admin"},  # extra key (strict forbids)
    {"assistants": ""},  # empty string
    {"assistants": "admin "},  # trailing whitespace
    {"assistants ": "admin"},  # trailing whitespace in key
    [],  # wrong outermost type — list
    "admin",  # wrong outermost type — str
    42,  # wrong outermost type — int
]


@pytest.mark.parametrize("payload", _MALFORMED_PAYLOADS, ids=repr)
@pytest.mark.parametrize("required", ["write", "admin"])
@pytest.mark.parametrize("resource_type", RESOURCE_PERMISSION_FIELDS)
def test_malformed_resource_permissions_never_allow_write_or_admin(
    payload: Any, required: str, resource_type: str
):
    """Any malformed payload must deny ``write`` / ``admin`` requests.

    Admin permission on the basic key is intentional — if the fine-grained
    logic bypasses malformed input without raising, we *would* fall back to
    the basic permission. Even then, the overpermission must only surface
    when the basic permission is itself admin AND the fine-grained path was
    designed to cap it — which is exactly the behaviour we want.

    This test fails the moment any malformed payload lets a write through
    without a corresponding basic-permission ceiling decision.
    """
    # Scenario: basic = 'read' so the basic ceiling is low. If the malformed
    # payload is silently bypassed without raising, the read key must NOT be
    # upgraded to write.
    outcome = _run_impl(
        basic_permission="read",
        resource_permissions=payload,
        resource_type=resource_type,
        required=required,
        flag_enabled=True,
    )
    assert outcome == "deny", (
        f"Malformed resource_permissions {payload!r} allowed "
        f"{required} on {resource_type!r} with a read-only key."
    )


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_random_garbage_payloads_never_raise_unexpected_exceptions(seed: int):
    """Deterministic PRNG fuzz over arbitrary payloads.

    Weaker invariant than "never escalate" — because the implementation treats
    a well-formed ``resource_permissions`` dict as **authoritative** (the basic
    permission is not a secondary ceiling when rp is set), a key with
    ``basic=read, rp={knowledge:admin}`` legitimately grants admin on
    knowledge. In normal flow this inconsistent state never exists (basic is
    derived from ``max(rp)`` at creation), but we test runtime behaviour here,
    not flow.

    What this test asserts:
      - ``check_resource_permission`` only raises ``ApiKeyValidationError`` or
        returns None — never leaks any other exception type to the caller.
      - The outcome (allow/deny) matches the oracle for every generated
        payload, proving no drift across the malformed + well-formed space.
    """
    rng = random.Random(seed)
    junk_values: list[Any] = [
        "admin",
        "write",
        "read",
        "none",
        "ADMIN",
        "unknown",
        "",
        None,
        True,
        False,
        0,
        1,
        [],
        ["admin"],
        {},
        {"x": "admin"},
        "a" * 50,
    ]
    keys_pool = list(RESOURCE_PERMISSION_FIELDS) + [
        "unknown",
        "admin",
        "spaces ",
        "assistants_v2",
        "",
    ]

    drift: list[str] = []
    for _ in range(200):
        n_keys = rng.randint(0, 5)
        payload = {
            rng.choice(keys_pool): rng.choice(junk_values) for _ in range(n_keys)
        }
        for required in ("read", "write", "admin"):
            for resource_type in RESOURCE_PERMISSION_FIELDS:
                # Use basic=admin so the oracle's basic-ceiling branch is
                # out of the way and we are isolating the fine-grained path.
                try:
                    actual = _run_impl(
                        basic_permission="admin",
                        resource_permissions=payload,
                        resource_type=resource_type,
                        required=required,
                        flag_enabled=True,
                    )
                except ApiKeyValidationError:
                    # Never leaks to caller — caught by _run_impl.
                    raise AssertionError("unreachable")  # pragma: no cover
                # The oracle cannot reproduce Pydantic's validation decisions
                # for malformed payloads; treat any exception-path outcome as
                # 'deny' and skip oracle comparison for clearly-malformed
                # shapes (e.g. non-dict outermost, unknown/typed-wrong values).
                try:
                    from intric.authentication.auth_models import (
                        ResourcePermissions,
                    )

                    ResourcePermissions.model_validate(payload)
                    rp_is_valid = True
                except Exception:
                    rp_is_valid = False
                if not rp_is_valid:
                    # Implementation must have denied (fail-closed on malformed).
                    if actual != "deny":
                        drift.append(
                            f"malformed payload allowed: payload={payload}, "
                            f"required={required}, resource={resource_type}"
                        )
                    continue
                expected = oracle_check(
                    basic_permission="admin",
                    resource_permissions=payload,
                    resource_type=resource_type,
                    required=required,
                    flag_enabled=True,
                )
                if actual != expected:
                    drift.append(
                        f"oracle drift: payload={payload}, "
                        f"required={required}, resource={resource_type}, "
                        f"oracle={expected} impl={actual}"
                    )

    assert not drift, (
        "Drift or malformed-allow detected:\n  - "
        + "\n  - ".join(drift[:10])
        + (f"\n  ... and {len(drift) - 10} more" if len(drift) > 10 else "")
    )


# ---------------------------------------------------------------------------
# Invariant 3: Unknown resource_type always denies (fail-closed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unknown_resource",
    ["assistant", "app", "space", "knowledges", "files", "", "admin"],
)
@pytest.mark.parametrize("required", ["read", "write", "admin"])
def test_unknown_resource_type_always_denies_when_rp_is_set(
    unknown_resource: str, required: str
):
    """Even if the key has ``{assistants: admin, apps: admin, ...}``, a check
    against an **unknown** resource_type must fail-closed (the whole point of
    granted_level=0 in the implementation)."""
    rp = dict.fromkeys(RESOURCE_PERMISSION_FIELDS, "admin")
    outcome = _run_impl(
        basic_permission="admin",
        resource_permissions=rp,
        resource_type=unknown_resource,
        required=required,
        flag_enabled=True,
    )
    assert outcome == "deny", (
        f"Unknown resource_type {unknown_resource!r} was allowed at "
        f"{required}. Must fail-closed (granted_level=0)."
    )
