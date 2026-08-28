import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, quote_plus, urlparse
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.audit.domain.action_types import ActionType
from eneo.authentication.auth_models import (
    ApiKeyListCursor,
    ApiKeyListResponse,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)
from eneo.authentication.auth_service import AuthService
from eneo.main.config import get_settings
from eneo.main.exceptions import (
    AuthenticationException,
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.modules.module import (
    ModuleInDB,
    ModuleInstallationConfig,
    ModuleTenantClientConfig,
)
from eneo.modules.module_auth import (
    MODULE_HANDOFF_AT_CLAIM,
    MODULE_TENANT_ID_CLAIM,
    MODULE_USER_ID_CLAIM,
    ModuleAuthBroker,
    ModuleRequestPrincipal,
    ModuleTicketRequest,
    module_audience,
)

TENANT_ID = uuid4()
MODULE_ID = uuid4()
MODULE_KEY = "tal-till-text"
SERVICE_KEY_ID = uuid4()
USER_ID = uuid4()
REDIRECT_URI = "https://ttt.example.com/auth/callback"
TEST_JWT_SECRET = "unit-test-secret-padded-to-the-hs256-minimum"


@pytest.fixture(autouse=True)
def secure_test_jwt_secret(monkeypatch):
    """Keep module-auth token tests independent of the developer .env secret."""
    monkeypatch.setattr(get_settings(), "jwt_secret", TEST_JWT_SECRET)
    monkeypatch.setattr("eneo.authentication.auth_service.JWT_SECRET", TEST_JWT_SECRET)


class FakeRedis:
    """Minimal async stand-in for the two Redis commands the broker uses."""

    def __init__(self):
        self.store = {}

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def getdel(self, key):
        return self.store.pop(key, None)


def make_module(**overrides):
    values = {
        "id": MODULE_ID,
        "name": MODULE_KEY,
        "created_at": None,
        "updated_at": None,
    }
    values.update(overrides)
    return ModuleInDB(**values)


def make_config(**overrides):
    values = {
        "tenant_id": TENANT_ID,
        "module_id": MODULE_ID,
        "redirect_uris": [REDIRECT_URI],
        "service_key_id": SERVICE_KEY_ID,
    }
    values.update(overrides)
    return ModuleTenantClientConfig(**values)


def make_user(**overrides):
    user = MagicMock()
    user.id = USER_ID
    user.tenant_id = TENANT_ID
    user.email = "user@example.com"
    user.username = "user"
    user.is_active = True
    for key, value in overrides.items():
        setattr(user, key, value)
    return user


def make_api_key(**overrides):
    key = MagicMock()
    key.id = SERVICE_KEY_ID
    key.tenant_id = TENANT_ID
    key.ownership = ApiKeyOwnership.SERVICE
    key.key_type = ApiKeyType.SK
    key.permission = ApiKeyPermission.WRITE
    key.rotated_from_key_id = None
    key.revoked_at = None
    key.suspended_at = None
    key.expires_at = None
    key.rotation_grace_until = None
    for k, v in overrides.items():
        setattr(key, k, v)
    return key


def make_api_key_record(**overrides) -> ApiKeyV2InDB:
    values = {
        "id": SERVICE_KEY_ID,
        "tenant_id": TENANT_ID,
        "ownership": ApiKeyOwnership.SERVICE,
        "key_prefix": "sk_",
        "key_suffix": "12345678",
        "name": "Module service key",
        "key_type": ApiKeyType.SK,
        "permission": ApiKeyPermission.WRITE,
        "scope_type": ApiKeyScopeType.TENANT,
        "state": ApiKeyState.ACTIVE,
        "key_hash": "test-hash",
        "hash_version": "hmac_sha256",
    }
    values.update(overrides)
    return ApiKeyV2InDB(**values)


def make_broker(module=None, config=None, user=None, redis=None):
    module_repo = AsyncMock()
    resolved_module = module if module is not None else make_module()
    module_repo.get_module.return_value = resolved_module
    module_repo.get_module_by_key.return_value = resolved_module
    module_repo.get_module_client_config.return_value = (
        config if config is not None else make_config()
    )

    user_repo = AsyncMock()
    user_repo.get_user_by_id_and_tenant_id.return_value = (
        user if user is not None else make_user()
    )
    user_repo.get_user_by_email.return_value = user if user is not None else make_user()

    audit_service = AsyncMock()
    user_service = AsyncMock()
    api_key_repo = AsyncMock()
    api_key_repo.get.return_value = make_api_key()
    auth_service = AuthService()

    broker = ModuleAuthBroker(
        redis_client=redis if redis is not None else FakeRedis(),
        module_repo=module_repo,
        api_key_repo=api_key_repo,
        user_repo=user_repo,
        user_service=user_service,
        auth_service=auth_service,
        audit_service=audit_service,
    )
    return broker


async def issue(broker, user=None, redirect_uri=REDIRECT_URI, state=None):
    return await broker.issue_ticket(
        user=user if user is not None else make_user(),
        module_key=MODULE_KEY,
        redirect_uri=redirect_uri,
        state=state,
    )


def issued_ticket(result):
    """Extract the ticket from redirect_target - its only carrier."""
    return parse_qs(urlparse(result.redirect_target).query)["ticket"][0]


class TestIssueTicket:
    async def test_resolves_public_key_before_using_internal_module_id(self):
        broker = make_broker()

        await issue(broker)

        broker.module_repo.get_module_by_key.assert_awaited_once_with(MODULE_KEY)
        broker.module_repo.get_module_client_config.assert_awaited_once_with(
            tenant_id=TENANT_ID, module_id=MODULE_ID
        )

    async def test_issues_ticket_with_redirect_target(self):
        broker = make_broker()
        result = await issue(broker)

        assert result.redirect_target.startswith(REDIRECT_URI + "?ticket=")
        assert result.expires_in > 0
        assert len(broker.redis_client.store) == 1
        # redirect_target is the ticket's only carrier.
        assert "ticket" not in result.model_dump()

    async def test_unknown_module_raises_not_found(self):
        broker = make_broker()
        broker.module_repo.get_module_by_key.return_value = None

        with pytest.raises(NotFoundException):
            await issue(broker)

        assert broker.redis_client.store == {}
        broker.module_repo.get_module_client_config.assert_not_awaited()
        broker.audit_service.log_async.assert_not_awaited()

    async def test_unconfigured_module_raises_bad_request(self):
        broker = make_broker(config=make_config(service_key_id=None))

        with pytest.raises(BadRequestException):
            await issue(broker)

    async def test_redirect_uri_is_normalized_before_allowlist_match(self):
        broker = make_broker()

        result = await issue(
            broker, redirect_uri="https://TTT.example.com/auth/callback/"
        )

        assert result.redirect_target.startswith(REDIRECT_URI + "?ticket=")

    async def test_unregistered_redirect_uri_rejected(self):
        broker = make_broker()

        with pytest.raises(BadRequestException):
            await issue(broker, redirect_uri="https://evil.example.com/callback")

    async def test_invalid_redirect_uri_rejected_as_bad_request(self):
        broker = make_broker()

        with pytest.raises(BadRequestException):
            await issue(
                broker,
                redirect_uri="https://ttt.example.com/auth/callback?ticket=x",
            )

    async def test_module_not_enabled_for_tenant_rejected(self):
        broker = make_broker()
        broker.module_repo.get_module_client_config.return_value = None

        with pytest.raises(UnauthorizedException):
            await issue(broker)

        assert broker.redis_client.store == {}
        broker.audit_service.log_async.assert_not_awaited()

    async def test_state_is_echoed_urlencoded_on_redirect_target(self):
        broker = make_broker()
        state = "abc/+&käll=1"

        result = await issue(broker, state=state)

        assert result.redirect_target.startswith(REDIRECT_URI + "?ticket=")
        assert result.redirect_target.endswith(f"&state={quote_plus(state)}")

    async def test_redirect_target_carries_no_state_when_not_supplied(self):
        broker = make_broker()

        result = await issue(broker)

        assert "state=" not in result.redirect_target


class TestExchangeTicket:
    async def test_full_handoff_yields_module_scoped_token(self):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))

        result = await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)

        assert result.module_key == MODULE_KEY
        assert result.tenant_id == TENANT_ID
        assert result.user.id == USER_ID
        # Token decodes only with the module audience...
        payload = broker.auth_service.get_jwt_payload(
            result.access_token,
            key=str(get_settings().jwt_secret),
            aud=module_audience("tal-till-text"),
        )
        assert payload.sub == "user@example.com"
        # The token carries the immutable identity resolved on every request.
        claims = broker.auth_service.get_verified_claims(
            result.access_token,
            key=str(get_settings().jwt_secret),
            aud=module_audience("tal-till-text"),
        )
        assert claims[MODULE_USER_ID_CLAIM] == str(USER_ID)
        assert claims[MODULE_TENANT_ID_CLAIM] == str(TENANT_ID)
        # ...and validate_module_user_token rejects it for another module.
        with pytest.raises(AuthenticationException):
            broker.validate_module_user_token(
                result.access_token, make_module(name="other-module")
            )

    async def test_ticket_is_single_use(self):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))
        await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)

        with pytest.raises(AuthenticationException):
            await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)

    async def test_unknown_ticket_rejected(self):
        broker = make_broker()

        with pytest.raises(AuthenticationException):
            await broker.exchange_ticket(api_key=make_api_key(), ticket="forged")

    async def test_personal_key_rejected(self):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))

        with pytest.raises(UnauthorizedException):
            await broker.exchange_ticket(
                api_key=make_api_key(ownership=ApiKeyOwnership.USER), ticket=ticket
            )

    @pytest.mark.parametrize(
        "key_overrides",
        [
            {"key_type": ApiKeyType.PK},
            {"permission": ApiKeyPermission.READ},
        ],
    )
    async def test_key_that_cannot_authenticate_exchange_is_rejected(
        self, key_overrides
    ):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))

        with pytest.raises(UnauthorizedException):
            await broker.exchange_ticket(
                api_key=make_api_key(**key_overrides), ticket=ticket
            )

    async def test_key_not_registered_for_module_rejected(self):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))

        with pytest.raises(UnauthorizedException):
            await broker.exchange_ticket(
                api_key=make_api_key(id=uuid4()), ticket=ticket
            )

    async def test_wrong_service_key_does_not_consume_ticket(self):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))

        with pytest.raises(UnauthorizedException):
            await broker.exchange_ticket(
                api_key=make_api_key(id=uuid4()), ticket=ticket
            )

        result = await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)
        assert result.module_key == MODULE_KEY

    async def test_rotated_successor_of_registered_key_accepted(self):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))

        rotated = make_api_key(id=uuid4(), rotated_from_key_id=SERVICE_KEY_ID)
        result = await broker.exchange_ticket(api_key=rotated, ticket=ticket)
        assert result.module_key == MODULE_KEY

    async def test_key_from_other_tenant_rejected(self):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))

        with pytest.raises(UnauthorizedException):
            await broker.exchange_ticket(
                api_key=make_api_key(tenant_id=uuid4()), ticket=ticket
            )

    async def test_inactive_user_rejected(self):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))
        broker.user_repo.get_user_by_id_and_tenant_id.return_value = make_user(
            is_active=False
        )

        with pytest.raises(AuthenticationException):
            await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)


class TestModuleResourceAuthentication:
    async def module_token(self, broker, *, module_name=MODULE_KEY, claims=None):
        if claims is None:
            claims = {
                MODULE_USER_ID_CLAIM: str(USER_ID),
                MODULE_TENANT_ID_CLAIM: str(TENANT_ID),
            }
        return broker.auth_service.create_access_token_for_user(
            make_user(),
            audience=module_audience(module_name),
            extra_claims=claims or None,
        )

    async def test_validates_both_credentials_and_live_state(self):
        broker = make_broker()
        token = await self.module_token(broker)

        principal = await broker.authenticate_resource_request(
            module_key=MODULE_KEY,
            access_token=token,
            api_key=make_api_key(),
        )

        assert principal.module.id == MODULE_ID
        assert principal.user.id == USER_ID
        assert principal.api_key.id == SERVICE_KEY_ID
        broker.module_repo.get_module_client_config.assert_awaited_once_with(
            tenant_id=TENANT_ID,
            module_id=MODULE_ID,
        )
        # The principal is resolved by the token's immutable identity claims,
        # never by email (which can move to a replacement account).
        broker.user_repo.get_user_by_id_and_tenant_id.assert_awaited_once_with(
            USER_ID, tenant_id=TENANT_ID
        )
        broker.user_repo.get_user_by_email.assert_not_called()
        broker.user_service.validate_active_identity.assert_awaited_once_with(
            principal.user,
            correlation_id="module-resource-auth",
        )

    async def test_rejects_token_for_another_module(self):
        broker = make_broker()
        token = await self.module_token(broker, module_name="another-module")

        with pytest.raises(AuthenticationException):
            await broker.authenticate_resource_request(
                module_key=MODULE_KEY,
                access_token=token,
                api_key=make_api_key(),
            )

    async def test_rejects_disabled_module_assignment(self):
        broker = make_broker()
        broker.module_repo.get_module_client_config.return_value = None

        with pytest.raises(UnauthorizedException):
            await broker.authenticate_resource_request(
                module_key=MODULE_KEY,
                access_token=await self.module_token(broker),
                api_key=make_api_key(),
            )

    async def test_rejects_unbound_service_key(self):
        broker = make_broker()

        with pytest.raises(UnauthorizedException):
            await broker.authenticate_resource_request(
                module_key=MODULE_KEY,
                access_token=await self.module_token(broker),
                api_key=make_api_key(id=uuid4()),
            )

    async def test_rejects_token_minted_for_another_tenant(self):
        broker = make_broker()
        token = await self.module_token(
            broker,
            claims={
                MODULE_USER_ID_CLAIM: str(USER_ID),
                MODULE_TENANT_ID_CLAIM: str(uuid4()),
            },
        )

        with pytest.raises(AuthenticationException):
            await broker.authenticate_resource_request(
                module_key=MODULE_KEY,
                access_token=token,
                api_key=make_api_key(),
            )

        broker.user_repo.get_user_by_id_and_tenant_id.assert_not_awaited()

    async def test_rejects_token_without_identity_claims(self):
        broker = make_broker()
        token = await self.module_token(broker, claims={})

        with pytest.raises(AuthenticationException):
            await broker.authenticate_resource_request(
                module_key=MODULE_KEY,
                access_token=token,
                api_key=make_api_key(),
            )

        broker.user_repo.get_user_by_id_and_tenant_id.assert_not_awaited()
        broker.user_repo.get_user_by_email.assert_not_called()

    async def test_stale_token_never_rebinds_to_replacement_account_with_same_email(
        self,
    ):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))
        exchanged = await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)

        # The original row is soft-deleted and a replacement account now owns
        # the email; only email-based resolution would accept the old token.
        broker.user_repo.get_user_by_id_and_tenant_id.return_value = None
        broker.user_repo.get_user_by_email.return_value = make_user(id=uuid4())

        with pytest.raises(AuthenticationException):
            await broker.authenticate_resource_request(
                module_key=MODULE_KEY,
                access_token=exchanged.access_token,
                api_key=make_api_key(),
            )

        broker.user_repo.get_user_by_email.assert_not_called()


class TestRefreshToken:
    def make_principal(self, broker, token, *, module=None):
        return ModuleRequestPrincipal(
            module=module if module is not None else make_module(),
            user=make_user(),
            api_key=make_api_key(),
            access_token=token,
        )

    def claims_of(self, broker, token, *, module_name=MODULE_KEY):
        return broker.auth_service.get_verified_claims(
            token,
            key=str(get_settings().jwt_secret),
            aud=module_audience(module_name),
        )

    def token_with_handoff(self, broker, handoff_at, *, module_name=MODULE_KEY):
        return broker.auth_service.create_access_token_for_user(
            make_user(),
            audience=module_audience(module_name),
            expires_in=get_settings().module_auth_token_expiry_minutes,
            extra_claims={
                MODULE_HANDOFF_AT_CLAIM: handoff_at,
                MODULE_USER_ID_CLAIM: str(USER_ID),
                MODULE_TENANT_ID_CLAIM: str(TENANT_ID),
            },
        )

    async def test_exchange_reports_fixed_session_ceiling(self):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))

        result = await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)

        settings = get_settings()
        assert result.expires_in == settings.module_auth_token_expiry_minutes * 60
        ceiling = result.session_expires_at.timestamp()
        expected = time.time() + settings.module_auth_max_session_hours * 3600
        assert abs(ceiling - expected) < 5
        claims = self.claims_of(broker, result.access_token)
        assert claims[MODULE_HANDOFF_AT_CLAIM] == pytest.approx(time.time(), abs=5)

    async def test_refresh_preserves_original_handoff_time(self):
        broker = make_broker()
        ticket = issued_ticket(await issue(broker))
        exchanged = await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)
        principal = await broker.authenticate_resource_request(
            module_key=MODULE_KEY,
            access_token=exchanged.access_token,
            api_key=make_api_key(),
        )

        refreshed = await broker.refresh_token(principal=principal)

        original = self.claims_of(broker, exchanged.access_token)
        renewed = self.claims_of(broker, refreshed.access_token)
        assert renewed[MODULE_HANDOFF_AT_CLAIM] == original[MODULE_HANDOFF_AT_CLAIM]
        assert renewed[MODULE_USER_ID_CLAIM] == original[MODULE_USER_ID_CLAIM]
        assert renewed[MODULE_TENANT_ID_CLAIM] == original[MODULE_TENANT_ID_CLAIM]
        assert refreshed.session_expires_at == exchanged.session_expires_at
        assert refreshed.module_key == MODULE_KEY
        assert refreshed.user.id == USER_ID

    async def test_refresh_near_ceiling_clips_token_expiry(self):
        broker = make_broker()
        settings = get_settings()
        remaining = 120
        handoff_at = int(
            time.time() - settings.module_auth_max_session_hours * 3600 + remaining
        )
        principal = self.make_principal(
            broker, self.token_with_handoff(broker, handoff_at)
        )

        result = await broker.refresh_token(principal=principal)

        assert 0 < result.expires_in <= remaining
        assert result.session_expires_at.timestamp() == pytest.approx(
            handoff_at + settings.module_auth_max_session_hours * 3600, abs=1
        )

    async def test_refresh_past_ceiling_requires_new_handoff(self):
        broker = make_broker()
        settings = get_settings()
        handoff_at = int(
            time.time() - settings.module_auth_max_session_hours * 3600 - 1
        )
        principal = self.make_principal(
            broker, self.token_with_handoff(broker, handoff_at)
        )

        with pytest.raises(AuthenticationException, match="maximum length"):
            await broker.refresh_token(principal=principal)

    async def test_expired_token_cannot_be_refreshed(self):
        broker = make_broker()
        expired = broker.auth_service.create_access_token_for_user(
            make_user(),
            audience=module_audience(MODULE_KEY),
            expires_in=-1,
        )

        with pytest.raises(AuthenticationException):
            await broker.authenticate_resource_request(
                module_key=MODULE_KEY,
                access_token=expired,
                api_key=make_api_key(),
            )

    async def test_legacy_token_without_handoff_claim_anchors_ceiling_at_iat(self):
        broker = make_broker()
        legacy = broker.auth_service.create_access_token_for_user(
            make_user(),
            audience=module_audience(MODULE_KEY),
            expires_in=get_settings().module_auth_token_expiry_minutes,
        )
        principal = self.make_principal(broker, legacy)

        result = await broker.refresh_token(principal=principal)

        legacy_iat = self.claims_of(broker, legacy)["iat"]
        renewed = self.claims_of(broker, result.access_token)
        assert renewed[MODULE_HANDOFF_AT_CLAIM] == int(legacy_iat)
        expected_ceiling = (
            int(legacy_iat) + get_settings().module_auth_max_session_hours * 3600
        )
        assert result.session_expires_at.timestamp() == pytest.approx(
            expected_ceiling, abs=1
        )

    async def test_refresh_rejects_token_minted_for_another_module(self):
        broker = make_broker()
        foreign = self.token_with_handoff(
            broker, int(time.time()), module_name="another-module"
        )
        principal = self.make_principal(broker, foreign)

        with pytest.raises(AuthenticationException):
            await broker.refresh_token(principal=principal)

    async def test_refresh_is_audited_as_security_event(self):
        broker = make_broker()
        principal = self.make_principal(
            broker, self.token_with_handoff(broker, int(time.time()))
        )

        await broker.refresh_token(principal=principal)

        assert broker.audit_service.log_async.await_count == 1
        kwargs = broker.audit_service.log_async.await_args.kwargs
        assert kwargs["action"] == ActionType.MODULE_AUTH_TOKEN_REFRESHED
        assert kwargs["tenant_id"] == TENANT_ID


class TestModuleInstallationConfig:
    def test_redirect_uris_are_normalized_and_deduplicated(self):
        config = ModuleInstallationConfig(
            redirect_uris=[
                "https://TTT.example.com/auth/callback/",
                "https://ttt.example.com/auth/callback",
            ],
            service_key_id=None,
        )

        assert config.redirect_uris == [REDIRECT_URI]

    def test_invalid_redirect_uri_is_rejected(self):
        with pytest.raises(ValidationError):
            ModuleInstallationConfig(
                redirect_uris=["https://ttt.example.com/auth/callback?ticket=x"],
                service_key_id=None,
            )

    def test_service_key_must_be_present_but_may_be_explicitly_null(self):
        with pytest.raises(ValidationError):
            ModuleInstallationConfig(redirect_uris=[REDIRECT_URI])

        unbound = ModuleInstallationConfig(
            redirect_uris=[REDIRECT_URI], service_key_id=None
        )
        assert unbound.service_key_id is None


class TestModuleTicketRequest:
    def test_state_defaults_to_none(self):
        request = ModuleTicketRequest(module_key=MODULE_KEY, redirect_uri=REDIRECT_URI)

        assert request.state is None

    def test_empty_module_key_is_rejected(self):
        with pytest.raises(ValidationError):
            ModuleTicketRequest(module_key="", redirect_uri=REDIRECT_URI)

    def test_internal_module_id_is_not_a_supported_request_field(self):
        with pytest.raises(ValidationError):
            ModuleTicketRequest.model_validate(
                {
                    "module_key": MODULE_KEY,
                    "module_id": str(MODULE_ID),
                    "redirect_uri": REDIRECT_URI,
                }
            )

    @pytest.mark.parametrize("state", ["", "s" * 513])
    def test_empty_or_oversized_state_rejected(self, state):
        with pytest.raises(ValidationError):
            ModuleTicketRequest(
                module_key=MODULE_KEY, redirect_uri=REDIRECT_URI, state=state
            )


class TestModuleServiceKeyRegistration:
    async def test_lists_keys_through_generic_bounded_repository_filters(self):
        broker = make_broker()
        cursor = ApiKeyListCursor(
            created_at=datetime.now(timezone.utc),
            key_id=SERVICE_KEY_ID,
        )
        broker.api_key_repo.list_paginated.return_value = []

        result = await broker.list_client_config_service_keys(
            tenant_id=TENANT_ID,
            limit=50,
            cursor=cursor,
            search="reports",
        )

        assert result == ApiKeyListResponse(
            items=[],
            limit=50,
            next_cursor=None,
            previous_cursor=cursor.serialize(),
            total_count=None,
        )
        expected_filters = {
            "tenant_id": TENANT_ID,
            "ownership": ApiKeyOwnership.SERVICE.value,
            "key_type": ApiKeyType.SK.value,
            "min_permission": ApiKeyPermission.WRITE.value,
            "effectively_active": True,
            "search": "reports",
        }
        broker.api_key_repo.list_paginated.assert_awaited_once_with(
            **expected_filters,
            limit=50,
            cursor=cursor,
        )
        broker.api_key_repo.count.assert_not_awaited()

    async def test_exact_lookup_returns_only_currently_eligible_key(self):
        broker = make_broker()
        broker.api_key_repo.get.return_value = make_api_key_record()

        result = await broker.get_client_config_service_key(
            tenant_id=TENANT_ID,
            service_key_id=SERVICE_KEY_ID,
        )

        assert result.id == SERVICE_KEY_ID
        broker.api_key_repo.get.assert_awaited_once_with(
            key_id=SERVICE_KEY_ID,
            tenant_id=TENANT_ID,
        )

    async def test_exact_lookup_hides_ineligible_key(self):
        broker = make_broker()
        broker.api_key_repo.get.return_value = make_api_key(
            permission=ApiKeyPermission.READ
        )

        result = await broker.get_client_config_service_key(
            tenant_id=TENANT_ID,
            service_key_id=SERVICE_KEY_ID,
        )

        assert result is None

    async def test_accepts_same_tenant_service_sk_with_write_permission(self):
        broker = make_broker()

        await broker.validate_client_config_service_key(
            tenant_id=TENANT_ID, service_key_id=SERVICE_KEY_ID
        )

        broker.api_key_repo.get.assert_awaited_once_with(
            key_id=SERVICE_KEY_ID, tenant_id=TENANT_ID, for_update=True
        )

    async def test_rejects_unknown_or_wrong_tenant_key(self):
        broker = make_broker()
        broker.api_key_repo.get.return_value = None

        with pytest.raises(BadRequestException, match="target tenant"):
            await broker.validate_client_config_service_key(
                tenant_id=TENANT_ID, service_key_id=SERVICE_KEY_ID
            )

    @pytest.mark.parametrize(
        ("key_overrides", "message"),
        [
            ({"ownership": ApiKeyOwnership.USER}, "service-owned"),
            ({"key_type": ApiKeyType.PK}, "sk_ key type"),
            ({"permission": ApiKeyPermission.READ}, "write or admin"),
        ],
    )
    async def test_rejects_key_that_can_never_exchange(self, key_overrides, message):
        broker = make_broker()
        broker.api_key_repo.get.return_value = make_api_key(**key_overrides)

        with pytest.raises(BadRequestException, match=message):
            await broker.validate_client_config_service_key(
                tenant_id=TENANT_ID, service_key_id=SERVICE_KEY_ID
            )

    @pytest.mark.parametrize(
        ("key_overrides", "message"),
        [
            ({"revoked_at": datetime.now(timezone.utc)}, "revoked"),
            ({"suspended_at": datetime.now(timezone.utc)}, "suspended"),
            (
                {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)},
                "expired",
            ),
        ],
    )
    async def test_rejects_key_that_cannot_authenticate_right_now(
        self, key_overrides, message
    ):
        """Binding a dead key would persist a config under which every ticket
        exchange fails at API-key authentication."""
        broker = make_broker()
        broker.api_key_repo.get.return_value = make_api_key(**key_overrides)

        with pytest.raises(BadRequestException, match=message):
            await broker.validate_client_config_service_key(
                tenant_id=TENANT_ID, service_key_id=SERVICE_KEY_ID
            )

    async def test_accepts_key_expiring_in_the_future(self):
        broker = make_broker()
        broker.api_key_repo.get.return_value = make_api_key(
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )

        await broker.validate_client_config_service_key(
            tenant_id=TENANT_ID, service_key_id=SERVICE_KEY_ID
        )
