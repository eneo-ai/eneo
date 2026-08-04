from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyType,
)
from eneo.authentication.auth_service import AuthService
from eneo.main.config import get_settings
from eneo.main.exceptions import (
    AuthenticationException,
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.modules.module import ModuleClientConfig, ModuleInDB, ModuleTenantClientConfig
from eneo.modules.module_auth import (
    ModuleAuthBroker,
    module_audience,
)

TENANT_ID = uuid4()
MODULE_ID = uuid4()
SERVICE_KEY_ID = uuid4()
USER_ID = uuid4()
REDIRECT_URI = "https://ttt.example.com/auth/callback"


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
        "name": "tal-till-text",
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
    for k, v in overrides.items():
        setattr(key, k, v)
    return key


def make_broker(module=None, config=None, user=None, redis=None):
    module_repo = AsyncMock()
    module_repo.get_module.return_value = (
        module if module is not None else make_module()
    )
    module_repo.get_module_client_config.return_value = (
        config if config is not None else make_config()
    )

    user_repo = AsyncMock()
    user_repo.get_user_by_id_and_tenant_id.return_value = (
        user if user is not None else make_user()
    )

    audit_service = AsyncMock()
    api_key_repo = AsyncMock()
    api_key_repo.get.return_value = make_api_key()
    auth_service = AuthService()

    broker = ModuleAuthBroker(
        redis_client=redis if redis is not None else FakeRedis(),
        module_repo=module_repo,
        api_key_repo=api_key_repo,
        user_repo=user_repo,
        auth_service=auth_service,
        audit_service=audit_service,
    )
    return broker


async def issue(broker, user=None, redirect_uri=REDIRECT_URI):
    return await broker.issue_ticket(
        user=user if user is not None else make_user(),
        module_id=MODULE_ID,
        redirect_uri=redirect_uri,
    )


class TestIssueTicket:
    async def test_issues_ticket_with_redirect_target(self):
        broker = make_broker()
        result = await issue(broker)

        assert result.redirect_target.startswith(REDIRECT_URI + "?ticket=")
        assert result.expires_in > 0
        assert len(broker.redis_client.store) == 1

    async def test_unknown_module_raises_not_found(self):
        broker = make_broker()
        broker.module_repo.get_module.return_value = None

        with pytest.raises(NotFoundException):
            await issue(broker)

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


class TestExchangeTicket:
    async def test_full_handoff_yields_module_scoped_token(self):
        broker = make_broker()
        ticket = (await issue(broker)).ticket

        result = await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)

        assert result.module == "tal-till-text"
        assert result.tenant_id == TENANT_ID
        assert result.user.id == USER_ID
        # Token decodes only with the module audience...
        payload = broker.auth_service.get_jwt_payload(
            result.access_token,
            key=str(get_settings().jwt_secret),
            aud=module_audience("tal-till-text"),
        )
        assert payload.sub == "user@example.com"
        # ...and validate_module_user_token rejects it for another module.
        with pytest.raises(AuthenticationException):
            broker.validate_module_user_token(
                result.access_token, make_module(name="other-module")
            )

    async def test_ticket_is_single_use(self):
        broker = make_broker()
        ticket = (await issue(broker)).ticket
        await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)

        with pytest.raises(AuthenticationException):
            await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)

    async def test_unknown_ticket_rejected(self):
        broker = make_broker()

        with pytest.raises(AuthenticationException):
            await broker.exchange_ticket(api_key=make_api_key(), ticket="forged")

    async def test_personal_key_rejected(self):
        broker = make_broker()
        ticket = (await issue(broker)).ticket

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
        ticket = (await issue(broker)).ticket

        with pytest.raises(UnauthorizedException):
            await broker.exchange_ticket(
                api_key=make_api_key(**key_overrides), ticket=ticket
            )

    async def test_key_not_registered_for_module_rejected(self):
        broker = make_broker()
        ticket = (await issue(broker)).ticket

        with pytest.raises(UnauthorizedException):
            await broker.exchange_ticket(
                api_key=make_api_key(id=uuid4()), ticket=ticket
            )

    async def test_wrong_service_key_does_not_consume_ticket(self):
        broker = make_broker()
        ticket = (await issue(broker)).ticket

        with pytest.raises(UnauthorizedException):
            await broker.exchange_ticket(
                api_key=make_api_key(id=uuid4()), ticket=ticket
            )

        result = await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)
        assert result.module == "tal-till-text"

    async def test_rotated_successor_of_registered_key_accepted(self):
        broker = make_broker()
        ticket = (await issue(broker)).ticket

        rotated = make_api_key(id=uuid4(), rotated_from_key_id=SERVICE_KEY_ID)
        result = await broker.exchange_ticket(api_key=rotated, ticket=ticket)
        assert result.module == "tal-till-text"

    async def test_key_from_other_tenant_rejected(self):
        broker = make_broker()
        ticket = (await issue(broker)).ticket

        with pytest.raises(UnauthorizedException):
            await broker.exchange_ticket(
                api_key=make_api_key(tenant_id=uuid4()), ticket=ticket
            )

    async def test_inactive_user_rejected(self):
        broker = make_broker()
        ticket = (await issue(broker)).ticket
        broker.user_repo.get_user_by_id_and_tenant_id.return_value = make_user(
            is_active=False
        )

        with pytest.raises(AuthenticationException):
            await broker.exchange_ticket(api_key=make_api_key(), ticket=ticket)


class TestModuleClientConfig:
    def test_redirect_uris_are_normalized_and_deduplicated(self):
        config = ModuleClientConfig(
            redirect_uris=[
                "https://TTT.example.com/auth/callback/",
                "https://ttt.example.com/auth/callback",
            ]
        )

        assert config.redirect_uris == [REDIRECT_URI]

    def test_invalid_redirect_uri_is_rejected(self):
        with pytest.raises(ValidationError):
            ModuleClientConfig(
                redirect_uris=["https://ttt.example.com/auth/callback?ticket=x"]
            )

    def test_update_values_preserve_omitted_fields(self):
        config = ModuleClientConfig(redirect_uris=[REDIRECT_URI])

        assert config.update_values() == {"redirect_uris": [REDIRECT_URI]}

    def test_update_values_keep_explicit_null(self):
        config = ModuleClientConfig(service_key_id=None)

        assert config.update_values() == {"service_key_id": None}

    def test_empty_update_has_no_values(self):
        assert ModuleClientConfig().update_values() == {}


class TestModuleServiceKeyRegistration:
    async def test_accepts_same_tenant_service_sk_with_write_permission(self):
        broker = make_broker()

        await broker.validate_client_config_service_key(
            tenant_id=TENANT_ID, service_key_id=SERVICE_KEY_ID
        )

        broker.api_key_repo.get.assert_awaited_once_with(
            key_id=SERVICE_KEY_ID, tenant_id=TENANT_ID
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
