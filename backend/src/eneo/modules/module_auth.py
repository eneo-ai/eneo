import hashlib
import json
import secrets
from typing import Optional
from urllib.parse import urlencode
from uuid import UUID

import redis.asyncio as aioredis
from pydantic import BaseModel, field_validator

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyV2InDB,
    JWTPayload,
)
from eneo.authentication.auth_service import AuthService
from eneo.main.config import get_settings, validate_redirect_uri
from eneo.main.exceptions import (
    AuthenticationException,
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.modules.module import ModuleInDB
from eneo.modules.module_repo import ModuleRepository
from eneo.users.user import UserInDB
from eneo.users.user_repo import UsersRepository

_TICKET_KEY_PREFIX = "module_auth_ticket:"
MODULE_AUDIENCE_PREFIX = "eneo-module:"


class ModuleTicketRequest(BaseModel):
    module_id: UUID
    redirect_uri: str

    @field_validator("redirect_uri")
    @classmethod
    def normalize_redirect_uri(cls, value: str) -> str:
        redirect_uri = validate_redirect_uri(value)
        if redirect_uri is None:
            raise ValueError("redirect_uri is required")
        return redirect_uri


class ModuleTicketResponse(BaseModel):
    ticket: str
    redirect_target: str
    expires_in: int


class ModuleTokenRequest(BaseModel):
    ticket: str


class ModuleTokenUser(BaseModel):
    id: UUID
    email: str
    username: Optional[str] = None


class ModuleTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    module: str
    tenant_id: UUID
    user: ModuleTokenUser


def module_audience(module_name: str) -> str:
    return f"{MODULE_AUDIENCE_PREFIX}{module_name}"


def _ticket_redis_key(ticket: str) -> str:
    # Store only a digest so a Redis snapshot cannot be replayed as tickets.
    return _TICKET_KEY_PREFIX + hashlib.sha256(ticket.encode()).hexdigest()


class ModuleAuthBroker:
    """SSO handoff between an Eneo session and a module BFF.

    A logged-in user gets a one-time, short-lived ticket bound to one module;
    the module exchanges it server-side - authenticated with the sk_ key
    registered for that module - for a short-lived, module-scoped user token.
    The module session itself never authorizes anything: module-facing
    endpoints re-validate the token on every call.
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        module_repo: ModuleRepository,
        user_repo: UsersRepository,
        auth_service: AuthService,
        audit_service: AuditService,
    ) -> None:
        self.redis_client = redis_client
        self.module_repo = module_repo
        self.user_repo = user_repo
        self.auth_service = auth_service
        self.audit_service = audit_service

    async def issue_ticket(
        self, user: UserInDB, module_id: UUID, redirect_uri: str
    ) -> ModuleTicketResponse:
        settings = get_settings()
        try:
            normalized_redirect_uri = validate_redirect_uri(redirect_uri)
        except ValueError as exc:
            raise BadRequestException(str(exc)) from exc
        if normalized_redirect_uri is None:
            raise BadRequestException("redirect_uri is invalid.")
        redirect_uri = normalized_redirect_uri

        module = await self.module_repo.get_module(module_id)
        if module is None:
            raise NotFoundException("Module not found.")

        config = await self.module_repo.get_module_client_config(
            tenant_id=user.tenant_id, module_id=module.id
        )
        if config is None:
            raise UnauthorizedException("Module is not enabled for this tenant.")

        if not config.redirect_uris or config.service_key_id is None:
            raise BadRequestException(
                "Module is not configured for login handoff "
                "(missing redirect_uris or service key registration)."
            )

        if redirect_uri not in config.redirect_uris:
            raise BadRequestException("redirect_uri is not registered for this module.")

        ticket = secrets.token_urlsafe(32)
        ttl = settings.module_auth_ticket_ttl_seconds
        payload = json.dumps(
            {
                "user_id": str(user.id),
                "tenant_id": str(user.tenant_id),
                "module_id": str(module.id),
            }
        )
        await self.redis_client.setex(_ticket_redis_key(ticket), ttl, payload)

        await self.audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            actor_type=ActorType.USER,
            action=ActionType.MODULE_AUTH_TICKET_ISSUED,
            entity_type=EntityType.MODULE,
            entity_id=module.id,
            description=f"Issued module login ticket for '{module.name}'",
            metadata={"module": {"id": str(module.id), "name": module.name}},
        )

        separator = "&" if "?" in redirect_uri else "?"
        redirect_target = f"{redirect_uri}{separator}{urlencode({'ticket': ticket})}"
        return ModuleTicketResponse(
            ticket=ticket, redirect_target=redirect_target, expires_in=ttl
        )

    async def exchange_ticket(
        self, api_key: ApiKeyV2InDB, ticket: str
    ) -> ModuleTokenResponse:
        settings = get_settings()

        if api_key.ownership != ApiKeyOwnership.SERVICE:
            raise UnauthorizedException(
                "Module ticket exchange requires a service (sk_) key."
            )

        ticket_key = _ticket_redis_key(ticket)
        raw = await self.redis_client.get(ticket_key)
        if raw is None:
            raise AuthenticationException("Invalid or expired module ticket.")

        data = json.loads(raw)
        module = await self.module_repo.get_module(UUID(data["module_id"]))
        tenant_id = UUID(data["tenant_id"])
        module_id = UUID(data["module_id"])
        config = await self.module_repo.get_module_client_config(
            tenant_id=tenant_id, module_id=module_id
        )

        # Binding: only the key registered for this module may exchange its
        # tickets. A rotated successor stays valid (it points back at the
        # registered key via rotated_from_key_id) until the operator updates
        # the registration.
        allowed_ids = {api_key.id, api_key.rotated_from_key_id} - {None}
        if (
            module is None
            or config is None
            or config.service_key_id is None
            or config.service_key_id not in allowed_ids
        ):
            raise UnauthorizedException("API key is not registered for this module.")

        if api_key.tenant_id != tenant_id:
            raise UnauthorizedException("API key belongs to a different tenant.")

        user = await self.user_repo.get_user_by_id_and_tenant_id(
            UUID(data["user_id"]), tenant_id=tenant_id
        )
        if user is None or not user.is_active:
            raise AuthenticationException("User is not active.")

        consumed = await self.redis_client.getdel(ticket_key)
        if consumed is None or consumed != raw:
            raise AuthenticationException("Invalid or expired module ticket.")

        expires_in_minutes = settings.module_auth_token_expiry_minutes
        access_token = self.auth_service.create_access_token_for_user(
            user,
            audience=module_audience(module.name),
            expires_in=expires_in_minutes,
        )

        await self.audit_service.log_async(
            tenant_id=tenant_id,
            actor_id=user.id,
            actor_type=ActorType.USER,
            action=ActionType.MODULE_AUTH_TOKEN_EXCHANGED,
            entity_type=EntityType.MODULE,
            entity_id=module.id,
            description=f"Module '{module.name}' exchanged a login ticket",
            metadata={
                "module": {"id": str(module.id), "name": module.name},
                "api_key_id": str(api_key.id),
            },
        )

        return ModuleTokenResponse(
            access_token=access_token,
            expires_in=expires_in_minutes * 60,
            module=module.name,
            tenant_id=tenant_id,
            user=ModuleTokenUser(id=user.id, email=user.email, username=user.username),
        )

    def validate_module_user_token(self, token: str, module: ModuleInDB) -> JWTPayload:
        """Validate a module user token for the given module.

        Module-facing endpoints call this on EVERY request (alongside the sk_
        key check) - the module session alone must never authorize anything.
        Raises AuthenticationException on any mismatch (signature, expiry, or
        audience minted for a different module).
        """
        settings = get_settings()
        return self.auth_service.get_jwt_payload(
            token,
            key=str(settings.jwt_secret),
            aud=module_audience(module.name),
        )
