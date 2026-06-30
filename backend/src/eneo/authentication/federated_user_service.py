"""Shared email-to-user resolution for federated (OIDC) identities.

Used by both the OIDC federation callback and the resource-server bearer
path so that allowed-domain checks, JIT provisioning, and tenant-membership
checks behave identically regardless of how the IdP identity arrived.
"""

import contextlib
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional
from uuid import UUID

from fastapi import HTTPException, status

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.main.exceptions import UniqueException
from eneo.main.logging import get_logger
from eneo.main.models import ModelId
from eneo.users.user import UserAdd, UserInDB, UserState

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.tenants.tenant import TenantInDB
    from eneo.tenants.tenant_repo import TenantRepository
    from eneo.users.user_repo import UsersRepository

logger = get_logger(__name__)

# Optional async hook for flow-level debug events ("domain_rejected", ...).
DebugLogger = Callable[..., Awaitable[None]]


async def _emit(debug: DebugLogger | None, event: str, **payload: Any) -> None:
    if debug is not None:
        await debug(event, **payload)


class FederatedUserService:
    """Resolve an IdP-asserted email to an Eneo user within a tenant.

    Raises ``fastapi.HTTPException`` with the same status codes and details
    as the federation callback historically produced, so both entry points
    surface identical errors.
    """

    def __init__(
        self,
        user_repo: "UsersRepository",
        tenant_repo: "TenantRepository",
        audit_service: Optional["AuditService"] = None,
    ):
        self.user_repo = user_repo
        self.tenant_repo = tenant_repo
        self.audit_service = audit_service

    async def resolve_user(
        self,
        *,
        email: str,
        tenant_id: UUID,
        allowed_domains: list[str] | None,
        correlation_id: str,
        tenant_slug: str | None = None,
        debug: DebugLogger | None = None,
    ) -> UserInDB:
        """Resolve ``email`` to a user of ``tenant_id``.

        Enforces, in order: email format, allowed email domains, user
        existence (with JIT provisioning when the tenant enables it), and
        tenant membership.
        """
        log_extra = {
            "tenant_id": str(tenant_id),
            "tenant_slug": tenant_slug,
            "correlation_id": correlation_id,
        }

        # Validate email format before domain checks (defensive against bad
        # IdP data)
        local_part, separator, domain_part = email.partition("@")
        if separator == "" or not domain_part or not local_part or "@" in domain_part:
            logger.error(
                "Email claim invalid format",
                extra={**log_extra, "email": email},
            )
            await _emit(debug, "email_invalid_format", email=email)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Email claim from identity provider is invalid. "
                    "Contact your administrator."
                ),
                headers={"X-Correlation-ID": correlation_id},
            )

        await self._check_allowed_domains(
            email=email,
            email_domain_raw=domain_part,
            allowed_domains=allowed_domains,
            correlation_id=correlation_id,
            tenant_slug=tenant_slug,
            log_extra=log_extra,
            debug=debug,
        )

        user = await self.user_repo.get_user_by_email(email)

        if not user:
            tenant = await self.tenant_repo.get(tenant_id)

            if tenant and tenant.provisioning:
                logger.info(
                    "JIT provisioning: Creating new user",
                    extra={**log_extra, "email": email},
                )
                await _emit(debug, "jit_provisioning", email=email)

                user = await self._jit_provision_user(
                    tenant=tenant,
                    email=email,
                    correlation_id=correlation_id,
                )
            else:
                logger.error(
                    "User not found (JIT provisioning disabled)",
                    extra={
                        **log_extra,
                        "email": email,
                        "provisioning_enabled": tenant.provisioning
                        if tenant
                        else False,
                    },
                )
                await _emit(debug, "user_missing", email=email)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User not found. Contact your administrator for access.",
                    headers={"X-Correlation-ID": correlation_id},
                )

        # Verify user belongs to correct tenant
        if user.tenant_id != tenant_id:
            logger.error(
                "User tenant mismatch",
                extra={
                    "user_tenant_id": str(user.tenant_id),
                    "expected_tenant_id": str(tenant_id),
                    "email": email,
                    "correlation_id": correlation_id,
                },
            )
            await _emit(
                debug,
                "user_tenant_mismatch",
                email=email,
                user_tenant_id=str(user.tenant_id),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied for this organization.",
                headers={"X-Correlation-ID": correlation_id},
            )

        return user

    async def _check_allowed_domains(
        self,
        *,
        email: str,
        email_domain_raw: str,
        allowed_domains: list[str] | None,
        correlation_id: str,
        tenant_slug: str | None,
        log_extra: dict[str, Any],
        debug: DebugLogger | None,
    ) -> None:
        if not allowed_domains:
            return

        email_domain = email_domain_raw.lower()
        try:
            email_domain = email_domain.encode("idna").decode("ascii")
        except Exception:  # pragma: no cover - defensive normalization
            pass

        normalized_allowed: list[str] = []
        for domain in allowed_domains:
            normalized = domain.lower()
            try:
                normalized = normalized.encode("idna").decode("ascii")
            except Exception:
                pass
            normalized_allowed.append(normalized)

        if email_domain not in normalized_allowed:
            logger.error(
                "Email domain not allowed for tenant",
                extra={
                    **log_extra,
                    "email_domain": email_domain,
                    "allowed_domains": normalized_allowed,
                },
            )
            await _emit(
                debug, "domain_rejected", email=email, email_domain=email_domain
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Email domain '{email_domain_raw}' is not allowed for this "
                    "organization. Contact your administrator to add your domain."
                ),
                headers={"X-Correlation-ID": correlation_id},
            )

        await _emit(debug, "domain_allowed", email=email, email_domain=email_domain)

    async def _jit_provision_user(
        self,
        *,
        tenant: "TenantInDB",
        email: str,
        correlation_id: str,
    ) -> UserInDB:
        """Create a user via JIT provisioning.

        Idempotent under concurrent first requests: a lost insert race
        (unique email constraint) recovers the winner's row, and only the
        request that actually created the user emits the audit entry.
        """
        roles = []
        if tenant.default_role_id:
            roles = [ModelId(id=tenant.default_role_id)]
            logger.info(
                "JIT provisioning: Assigning default role",
                extra={
                    "correlation_id": correlation_id,
                    "default_role_id": str(tenant.default_role_id),
                },
            )
        else:
            # WARNING (not INFO): a role-less user cannot create shared
            # spaces, use assistants, apps, or any other permission-gated
            # feature. See S7 rationale in user_service.py.
            logger.warning(
                "JIT provisioning: No default role configured; creating user "
                "without role — user will have zero permissions until an "
                "admin assigns roles",
                extra={
                    "correlation_id": correlation_id,
                    "tenant_id": str(tenant.id),
                },
            )

        username = email.split("@")[0].lower()

        new_user = UserAdd(
            email=email,
            username=username,
            tenant_id=tenant.id,
            roles=roles,
            state=UserState.ACTIVE,
        )

        try:
            user_in_db = await self.user_repo.add(new_user)
        except UniqueException:
            existing = await self._recover_concurrently_created_user(
                email=email, correlation_id=correlation_id
            )
            if existing is not None:
                return existing
            # Not an email race (e.g. username collision across domains):
            # surface the same failure as any other creation error.
            logger.error(
                "JIT provisioning failed: unique constraint violation without "
                "an existing user for the email",
                extra={
                    "correlation_id": correlation_id,
                    "email": email,
                    "tenant_id": str(tenant.id),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user account",
                headers={"X-Correlation-ID": correlation_id},
            )
        except Exception as e:
            logger.error(
                "JIT provisioning failed: Could not create user",
                extra={
                    "correlation_id": correlation_id,
                    "email": email,
                    "tenant_id": str(tenant.id),
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user account",
                headers={"X-Correlation-ID": correlation_id},
            )

        logger.info(
            "JIT provisioning: Created user",
            extra={
                "correlation_id": correlation_id,
                "user_id": str(user_in_db.id),
                "email": email,
                "username": username,
                "tenant_id": str(tenant.id),
            },
        )

        await self._log_user_created(
            tenant_id=tenant.id, user=user_in_db, correlation_id=correlation_id
        )

        return user_in_db

    async def _recover_concurrently_created_user(
        self, *, email: str, correlation_id: str
    ) -> UserInDB | None:
        """Refetch the user after a lost insert race.

        The failed INSERT aborts the surrounding transaction, so roll back
        (best effort) before querying again.
        """
        session = getattr(self.user_repo, "session", None)
        if session is not None:
            with contextlib.suppress(Exception):
                await session.rollback()

        user = await self.user_repo.get_user_by_email(email)
        if user is not None:
            logger.info(
                "JIT provisioning: concurrent request created the user; "
                "reusing existing row",
                extra={
                    "correlation_id": correlation_id,
                    "user_id": str(user.id),
                    "email": email,
                },
            )
        return user

    async def _log_user_created(
        self, *, tenant_id: UUID, user: UserInDB, correlation_id: str
    ) -> None:
        """Log audit event for a JIT-provisioned user. Non-blocking on failure."""
        if self.audit_service is None:
            logger.warning(
                "Failed to log JIT user creation audit event: no audit service",
                extra={
                    "correlation_id": correlation_id,
                    "user_id": str(user.id),
                    "email": user.email,
                },
            )
            return

        try:
            await self.audit_service.log(
                tenant_id=tenant_id,
                actor_id=None,
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=user.id,
                description=f"User '{user.email}' auto-provisioned via SSO federation",
                metadata={
                    "provisioning_method": "jit_federation",
                    "correlation_id": correlation_id,
                    "email": user.email,
                    "username": user.username,
                },
                outcome=Outcome.SUCCESS,
                actor_type=ActorType.SYSTEM,
            )
        except Exception as e:
            logger.warning(
                "Failed to log JIT user creation audit event",
                extra={
                    "correlation_id": correlation_id,
                    "user_id": str(user.id),
                    "email": user.email,
                    "error": str(e),
                },
            )
