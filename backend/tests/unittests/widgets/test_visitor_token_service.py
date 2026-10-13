from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest

from eneo.widgets.application.visitor_token_service import (
    TOKEN_USE,
    VisitorTokenService,
    visitor_token_key,
    widget_audience,
)
from eneo.widgets.domain.exceptions import (
    VisitorTokenInvalidError,
    VisitorTokenStaleError,
)
from eneo.widgets.domain.widget import Widget

SECRET = "unit-test-secret-with-at-least-thirty-two-bytes"


def _settings(ttl: int = 900) -> SimpleNamespace:
    return SimpleNamespace(
        jwt_secret=SECRET,
        widget_visitor_token_ttl_seconds=ttl,
        widget_visitor_token_grace_seconds=3600,
        widget_preview_token_ttl_seconds=3600,
    )


def _widget(**overrides) -> Widget:
    widget = Widget.create(
        tenant_id=uuid4(), space_id=uuid4(), target_id=uuid4(), name="w"
    )
    return widget.model_copy(update={"id": uuid4(), **overrides})


def _encode(widget: Widget, *, key: str | None = None, **overrides) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "token_use": TOKEN_USE,
        "aud": widget_audience(widget.id),
        "sub": str(uuid4()),
        "wid": str(widget.id),
        "tid": str(widget.tenant_id),
        "gen": widget.token_generation,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "jti": "x",
    }
    payload.update(overrides)
    return jwt.encode(payload, key or visitor_token_key(_settings()), algorithm="HS256")


def test_mint_and_verify_round_trip():
    widget = _widget()
    service = VisitorTokenService(settings=_settings())
    visitor_id = uuid4()

    token, expires_in = service.mint(widget, visitor_id)
    assert expires_in == 900
    claims = service.verify(token, widget)
    assert claims.visitor_id == visitor_id
    assert claims.widget_id == widget.id
    assert claims.tenant_id == widget.tenant_id
    assert claims.generation == 0
    assert claims.expires_at > datetime.now(timezone.utc)


def test_preview_tokens_are_flagged_and_live_longer():
    widget = _widget()
    service = VisitorTokenService(settings=_settings())

    token, expires_in = service.mint(widget, uuid4(), preview=True)
    assert expires_in == 3600
    assert service.verify(token, widget).preview is True

    ordinary, _ = service.mint(widget, uuid4())
    assert service.verify(ordinary, widget).preview is False
    # A forged flag with the wrong type never counts as a preview.
    assert service.verify(_encode(widget, preview="yes"), widget).preview is False


def test_token_is_bound_to_one_widget():
    service = VisitorTokenService(settings=_settings())
    widget, other = _widget(), _widget()
    token, _ = service.mint(widget, uuid4())
    with pytest.raises(VisitorTokenInvalidError):
        service.verify(token, other)


def test_stale_generation_is_rejected_but_identifiable():
    service = VisitorTokenService(settings=_settings())
    widget = _widget()
    token, _ = service.mint(widget, uuid4())
    bumped = widget.model_copy(update={"token_generation": 1})
    with pytest.raises(VisitorTokenStaleError):
        service.verify(token, bumped)


def test_expired_token_honours_grace_only_when_asked():
    service = VisitorTokenService(settings=_settings())
    widget = _widget()
    past = datetime.now(timezone.utc) - timedelta(minutes=30)
    token = _encode(widget, exp=int(past.timestamp()))

    with pytest.raises(VisitorTokenInvalidError):
        service.verify(token, widget)
    claims = service.verify(token, widget, grace_seconds=3600)
    assert claims.expires_at < datetime.now(timezone.utc)

    long_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    with pytest.raises(VisitorTokenInvalidError):
        service.verify(
            _encode(widget, exp=int(long_ago.timestamp())), widget, grace_seconds=3600
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"token_use": "access"},
        {"wid": str(uuid4())},
        {"tid": str(uuid4())},
        {"sub": "not-a-uuid"},
    ],
)
def test_claim_mismatches_are_invalid(overrides):
    service = VisitorTokenService(settings=_settings())
    widget = _widget()
    with pytest.raises(VisitorTokenInvalidError):
        service.verify(_encode(widget, **overrides), widget)


def test_tampered_and_foreign_tokens_are_invalid():
    service = VisitorTokenService(settings=_settings())
    widget = _widget()
    token, _ = service.mint(widget, uuid4())
    with pytest.raises(VisitorTokenInvalidError):
        service.verify(token[:-3] + "abc", widget)
    foreign = jwt.encode(
        {"aud": widget_audience(widget.id), "sub": "x", "exp": 9999999999, "iat": 1},
        "another-deployment-secret-of-thirty-two-bytes",
        algorithm="HS256",
    )
    with pytest.raises(VisitorTokenInvalidError):
        service.verify(foreign, widget)


def test_visitor_tokens_are_not_signed_with_the_user_session_secret():
    widget = _widget()
    service = VisitorTokenService(settings=_settings())
    token, _ = service.mint(widget, uuid4())

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            token,
            key=SECRET,
            audience=widget_audience(widget.id),
            algorithms=["HS256"],
        )
    # Nor is a token signed with the user-session secret a visitor token.
    with pytest.raises(VisitorTokenInvalidError):
        service.verify(_encode(widget, key=SECRET), widget)
