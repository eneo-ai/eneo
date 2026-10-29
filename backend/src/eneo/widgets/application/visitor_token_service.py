# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import jwt

from eneo.main.config import Settings, get_settings
from eneo.widgets.domain.exceptions import (
    VisitorTokenInvalidError,
    VisitorTokenStaleError,
)
from eneo.widgets.domain.visitor import VisitorClaims
from eneo.widgets.domain.widget import Widget

TOKEN_USE = "widget_visitor"
# The key is a derived HMAC secret, so the algorithm is fixed with it.
ALGORITHM = "HS256"


def widget_audience(widget_id: UUID) -> str:
    return f"eneo-widget:{widget_id}"


def visitor_token_key(settings: Settings) -> str:
    """Visitor tokens get their own key: a user-session decode can never
    accept one, whatever audience checks it skips."""
    return hashlib.sha256(
        f"eneo-widget-token:{settings.jwt_secret}".encode()
    ).hexdigest()


class VisitorTokenService:
    """Mints and verifies the short-lived JWT a widget visitor holds.

    The token is bound to one widget (audience), one pseudonymous visitor
    (``sub``) and the widget's ``token_generation``; pausing or changing
    visitor-facing configuration bumps the generation and every outstanding
    token becomes stale on its next use.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    def mint(
        self, widget: Widget, visitor_id: UUID, *, preview: bool = False
    ) -> tuple[str, int]:
        assert widget.id is not None
        ttl = (
            self.settings.widget_preview_token_ttl_seconds
            if preview
            else self.settings.widget_visitor_token_ttl_seconds
        )
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "token_use": TOKEN_USE,
            "aud": widget_audience(widget.id),
            "sub": str(visitor_id),
            "wid": str(widget.id),
            "tid": str(widget.tenant_id),
            "gen": widget.token_generation,
            # Two seconds of skew so a token is never "not yet valid".
            "iat": int((now - timedelta(seconds=2)).timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
            "jti": uuid4().hex,
        }
        if preview:
            payload["preview"] = True
        token = jwt.encode(
            payload, visitor_token_key(self.settings), algorithm=ALGORITHM
        )
        return token, ttl

    def verify(
        self, token: str, widget: Widget, *, grace_seconds: int = 0
    ) -> VisitorClaims:
        """Verify ``token`` for ``widget``.

        ``grace_seconds`` lets an expired token still identify the visitor for
        a silent re-mint; request authorization always passes 0.
        """
        assert widget.id is not None
        try:
            claims = jwt.decode(
                token,
                key=visitor_token_key(self.settings),
                audience=widget_audience(widget.id),
                algorithms=[ALGORITHM],
                options={"verify_exp": False, "require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise VisitorTokenInvalidError() from exc

        if (
            claims.get("token_use") != TOKEN_USE
            or claims.get("wid") != str(widget.id)
            or claims.get("tid") != str(widget.tenant_id)
        ):
            raise VisitorTokenInvalidError()

        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
        if expires_at + timedelta(seconds=grace_seconds) < now:
            raise VisitorTokenInvalidError("Visitor token has expired.")

        try:
            generation = int(claims.get("gen", -1))
            visitor_id = UUID(str(claims["sub"]))
        except (TypeError, ValueError) as exc:
            raise VisitorTokenInvalidError() from exc
        if generation != widget.token_generation:
            raise VisitorTokenStaleError()

        return VisitorClaims(
            widget_id=widget.id,
            tenant_id=widget.tenant_id,
            visitor_id=visitor_id,
            generation=generation,
            issued_at=datetime.fromtimestamp(int(claims["iat"]), tz=timezone.utc),
            expires_at=expires_at,
            jti=str(claims.get("jti", "")),
            preview=claims.get("preview") is True,
        )
