"""Server-side browser sessions: one ``browser_sessions`` row per sign-in.

The token a browser sign-in issues carries a ``sid`` claim naming its row,
and the row's stable, non-secret id as ``session_ref`` (tokens issued before
rows had one carry the sid alone). Canonical authentication (``UserService``)
admits such a token, as the cookie or as Bearer, only while the row exists,
matches the token's user, tenant and ``session_ref`` and is unexpired.
Sign-out deletes the row, so a copied token stops working at once. Every
sign-in a person makes starts one (the cookie and token logins, password or
OIDC). Tokens without ``sid`` (API, module and MCP tokens, the provider-bound
login's, and tokens issued before sign-ins started sessions) are not browser
sessions and keep their own lifetime.

The rows live in PostgreSQL, not Redis: a revoked session must stay revoked
after a crash, and restoring a Redis snapshot can bring a deleted key back.

Staying signed in (``POST /auth/session/extend/``) renews the same session:
the new token keeps its ``sid`` and the row's expiry moves to the new token's,
never earlier. A session whose row is gone (signed out) or expired cannot
renew itself.

Admission is checked when a request authenticates. Finite HTTP and SSE work
admitted before sign-out may still finish. The job-event stream
(``GET /jobs/events/``) and the socket (``/ws``) stay open until the client
leaves, so while they serve a browser session they re-run authentication
(``SessionWatch``) and end at the token's expiry; the socket closes with 1008.
"""

import asyncio
import contextlib
import secrets
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import sqlalchemy as sa
from dependency_injector import providers
from fastapi import HTTPException, status
from starlette.requests import HTTPConnection

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import JWTPayload
from eneo.authentication.auth_service import AuthService
from eneo.authentication.browser_session import session_generation
from eneo.database.affected_rows import affected_row_count
from eneo.database.database import AsyncSession, sessionmanager
from eneo.database.tables.browser_sessions_table import BrowserSessions
from eneo.main.config import get_settings
from eneo.main.exceptions import AuthenticationException
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.users.user import UserInDB

logger = get_logger(__name__)

# How often a response that stays open re-runs admission for its session.
RECHECK_SECONDS = 30.0
# How long sign-out or that check waits for the database, from taking a
# connection to the commit, before it gives up (503, or the response ends).
STORE_DEADLINE_SECONDS = 5.0


@contextlib.asynccontextmanager
async def _store_transaction(session: AsyncSession) -> AsyncGenerator[None]:
    """A transaction on ``session`` that ends within ``STORE_DEADLINE_SECONDS``.

    The database itself gives up on a statement, a lock wait included, after
    half of it, so a slow store normally fails as an error the transaction
    rolls back. The deadline covers the rest (the connection, the commit, a
    store that stops answering); its cancellation rolls back as well, and the
    connection goes back to the pool when the session closes.
    """
    async with asyncio.timeout(STORE_DEADLINE_SECONDS), session.begin():
        limit = str(int(STORE_DEADLINE_SECONDS * 500))
        await session.execute(
            sa.text(
                "SELECT set_config('lock_timeout', :limit, true),"
                " set_config('statement_timeout', :limit, true)"
            ),
            {"limit": limit},
        )
        yield


def _same_session(payload: JWTPayload) -> list[sa.ColumnElement[bool]]:
    """The row a verified session token names: its sid, user and tenant,
    and its stable id when the token carries one."""
    conditions = [
        BrowserSessions.sid == payload.sid,
        BrowserSessions.user_id == payload.user_id,
        BrowserSessions.tenant_id == payload.tenant_id,
    ]
    if payload.session_ref is not None:
        conditions.append(BrowserSessions.id == payload.session_ref)
    return conditions


class BrowserSessionService:
    def __init__(
        self,
        session: AsyncSession,
        auth_service: AuthService,
        audit_service: "AuditService",
    ):
        self.session = session
        self.auth_service = auth_service
        self.audit_service = audit_service

    async def start(self, token: str, replacing: str | None = None) -> str:
        """Record a browser session for the token a sign-in just issued.

        Returns the token the session cookie carries: the same claims and
        expiry with a new ``sid`` and the new row's stable id as
        ``session_ref``. Runs in the sign-in's transaction, so the cookie is
        sent only once the row is committed. The session ``replacing`` (the
        cookie the browser signed in with) names is deleted too: the new
        cookie replaces it, so it would otherwise stay valid with nobody
        holding it. Expired rows are left to ``delete_expired``.
        """
        payload = self._verified_payload(token)
        replaced = self._named_session(replacing) if replacing else None
        if replaced is not None:
            await self.session.execute(
                sa.delete(BrowserSessions).where(*_same_session(replaced))
            )
        # 256 bits; JWTCreds.sid accepts exactly this form.
        sid = secrets.token_urlsafe(32)
        session_ref = await self.session.scalar(
            sa.insert(BrowserSessions)
            .values(
                sid=sid,
                user_id=payload.user_id,
                tenant_id=payload.tenant_id,
                expires_at=datetime.fromtimestamp(payload.exp, timezone.utc),
            )
            .returning(BrowserSessions.id)
        )
        return self.auth_service.add_session_id(token, sid, session_ref)

    async def admit(self, payload: JWTPayload) -> None:
        """Refuse a verified token whose browser session has ended.

        The row must exist, belong to the token's user and tenant, be the one
        its ``session_ref`` names when it carries one, and be unexpired.
        Independent of ``BROWSER_SESSION_ENABLED``: a ``sid`` token presented
        as Bearer is checked all the same.
        """
        if (
            payload.sid is None
            or await self.session.scalar(
                sa.select(BrowserSessions.sid).where(
                    *_same_session(payload),
                    BrowserSessions.expires_at > datetime.now(timezone.utc),
                )
            )
            is None
        ):
            raise AuthenticationException("Could not validate token credentials.")

    async def delete_expired(self) -> int:
        """Delete every expired session, in the caller's transaction, and
        return how many there were. An expired row admits nothing, so this
        only keeps the table small."""
        result = await self.session.execute(
            sa.delete(BrowserSessions).where(
                BrowserSessions.expires_at <= datetime.now(timezone.utc)
            )
        )
        return affected_row_count(result)

    async def renew(self, current: JWTPayload, token: str, user: "UserInDB") -> str:
        """Renew the browser session ``current`` names with ``token``.

        ``token`` was just issued to ``user`` to replace the admitted session
        token ``current``. Returns it carrying the same ``sid`` and
        ``session_ref`` (none, for a session started before sessions had
        one), so the session (and its sign-out) stays the same one. The
        session's row moves to the new token's expiry unless another renewal
        already moved it later (renewals can be recorded in another order
        than they were issued), and the renewal is audited, in one
        transaction that commits within ``STORE_DEADLINE_SECONDS``, before
        the caller sets the cookie.
        A session that has ended meanwhile (its row is gone or expired) is
        refused, and nothing is written.

        Commits on its own: the caller's session must have no transaction open.
        """
        if current.sid is None:
            raise AuthenticationException("No browser session")
        renewed = self.auth_service.add_session_id(
            token, current.sid, current.session_ref
        )
        expires_at = datetime.fromtimestamp(
            self._verified_payload(renewed).exp, timezone.utc
        )
        try:
            async with _store_transaction(self.session):
                moved = await self.session.scalar(
                    sa.update(BrowserSessions)
                    .where(
                        *_same_session(current),
                        BrowserSessions.expires_at > datetime.now(timezone.utc),
                    )
                    .values(
                        expires_at=sa.func.greatest(
                            BrowserSessions.expires_at, expires_at
                        )
                    )
                    .returning(BrowserSessions.sid)
                )
                if moved is None:
                    raise AuthenticationException("The browser session has ended.")
                await self.audit_service.log(
                    tenant_id=user.tenant_id,
                    user=user,
                    action=ActionType.SESSION_EXTENDED,
                    entity_type=EntityType.USER,
                    entity_id=user.id,
                    description="Extended the browser session at the user's request",
                    metadata=AuditMetadata.authentication(
                        actor=user,
                        method="browser_session_extension",
                        success=True,
                        # Which of the user's sessions, by the fingerprint its
                        # pages send (never the sid), and its new end.
                        extra={
                            "session_generation": session_generation(renewed),
                            "expires_at": expires_at.isoformat(),
                        },
                    ),
                )
        except AuthenticationException:
            raise
        except Exception as exc:
            # A store error renders its statement's parameters, the sid among
            # them, so only its type is logged, as sign-out does.
            logger.error(
                "browser_session_extend_unavailable",
                extra={
                    "user_id": str(current.user_id),
                    "tenant_id": str(current.tenant_id),
                    "error_type": type(exc).__name__,
                },
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "session_extend_unavailable",
                    "message": "The session could not be extended. Try again.",
                },
            ) from None
        return renewed

    async def revoke(self, token: str) -> None:
        """Delete the session a sign-out's token names.

        Only a token that meets the local-token contract (signature, issuer,
        audience, typed claims) names a session; any other cookie, or a token
        without ``sid``, has nothing to revoke. Unlike authentication and
        renewal, sign-out also takes a token that has expired, for as long
        again as it was valid: a renewal keeps the ``sid``, so a sign-out sent
        with the token it replaced, which expired on the way, still ends the
        renewed session. A copy that expired longer ago ends nothing. The
        account is not checked, so a restricted user can still sign out. A row
        already gone is success: a retry after a lost response still signs out.

        Commits on its own, outside any request transaction. When the deletion
        cannot be confirmed within ``STORE_DEADLINE_SECONDS``, raises 503: the
        cookie stays, as the handle for a retry.
        """
        payload = self._named_session(token)
        if payload is None:
            return
        try:
            async with _store_transaction(self.session):
                await self.session.execute(
                    sa.delete(BrowserSessions).where(*_same_session(payload))
                )
        except Exception as exc:
            logger.error(
                "browser_sign_out_unavailable",
                extra={
                    "user_id": str(payload.user_id),
                    "tenant_id": str(payload.tenant_id),
                    "error_type": type(exc).__name__,
                },
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "sign_out_unavailable",
                    "message": "Sign-out could not be completed. Try again.",
                },
            ) from exc

    def _named_session(self, token: str) -> JWTPayload | None:
        """The session a cookie's token names, or None.

        Only a token that meets the local-token contract (signature, issuer,
        audience, typed claims) and carries a ``sid`` names one. An expired
        token still does, for as long again as it was valid: a renewal keeps
        the ``sid``, so the token it replaced, expired on the way, still
        names the renewed session.
        """
        try:
            payload = self._verified_payload(token, verify_exp=False)
        except AuthenticationException:
            return None
        lifetime = payload.exp - payload.iat
        if payload.sid is None or time.time() >= payload.exp + lifetime:
            return None
        return payload

    def _verified_payload(self, token: str, *, verify_exp: bool = True) -> JWTPayload:
        settings = get_settings()
        payload, _ = self.auth_service.get_jwt_payload_with_claims(
            token,
            key=str(settings.jwt_secret),
            aud=settings.jwt_audience,
            algs=[settings.jwt_algorithm],
            verify_exp=verify_exp,
        )
        return payload


class SessionWatch:
    """Whether a response that stays open may still serve the browser session
    its request was admitted under.

    The response asks between messages. Every ``RECHECK_SECONDS`` the
    request's authentication runs again for the token's claims
    (``UserService.authenticate_payload``), in a database session of its own
    held only for that check, so what refuses a new request ends the response
    too: sign-out, a password change, signing out everywhere, a deactivated
    account or a suspended tenant. In between, the answer is the clock against
    the token's expiry. A refusal, the expiry or a check that fails or does
    not finish within ``STORE_DEADLINE_SECONDS`` ends the response, and the
    client reconnects through ordinary authentication.

    The expiry is the admitted token's, not the row's: a renewal issues a new
    token for the session, and a response opened with the old one still ends
    when it does. The client reconnects with the renewed cookie, so no token
    serves past its own ``exp``.
    """

    def __init__(self, payload: JWTPayload, connection: HTTPConnection):
        self._payload = payload
        self._connection = connection
        self._admitted = True
        # The request has just authenticated.
        self._next_check = time.monotonic() + RECHECK_SECONDS

    async def __call__(self) -> bool:
        if not self._admitted or time.time() >= self._payload.exp:
            return False
        if time.monotonic() >= self._next_check:
            self._next_check = time.monotonic() + RECHECK_SECONDS
            self._admitted = await self._recheck()
        # The check can finish after the token expired.
        return self._admitted and time.time() < self._payload.exp

    async def _recheck(self) -> bool:
        # The container module imports this one.
        from eneo.main.container.request_container import request_container

        try:
            async with sessionmanager.session() as session, _store_transaction(session):
                container = request_container(session=providers.Object(session))
                await container.user_service().authenticate_payload(
                    self._payload, self._connection
                )
            return True
        except AuthenticationException:
            return False
        except Exception as exc:
            logger.warning(
                "browser_session_recheck_failed",
                extra={
                    "user_id": str(self._payload.user_id),
                    "tenant_id": str(self._payload.tenant_id),
                    "error_type": type(exc).__name__,
                },
            )
            return False
