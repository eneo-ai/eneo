"""Behavior contracts for membership admission through both OIDC login paths."""

from collections.abc import Sequence
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.authentication.auth_models import AccessToken, FederatedIdentity
from eneo.main.config import Settings
from eneo.main.exceptions import FederatedLoginDenied
from eneo.settings.credential_resolver import CredentialResolver
from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.users.user import UserAdd, UserInDB, UserState
from eneo.users.user_repo import UsersRepository
from eneo.users.user_service import UserService
from tests.fixtures import TEST_TENANT, TEST_USER


class UsersInMemory:
    def __init__(self, tenant: TenantInDB, users: Sequence[UserInDB] = ()):
        self.tenant = tenant
        self.users = list(users)
        self.created: list[UserAdd] = []

    async def get_user_by_email(self, email: str) -> UserInDB | None:
        return next(
            (
                user
                for user in self.users
                if user.email.lower() == email.lower() and user.deleted_at is None
            ),
            None,
        )

    async def has_removed_user_by_email(self, email: str, tenant_id: UUID) -> bool:
        return any(
            user.email.lower() == email.lower()
            and user.tenant_id == tenant_id
            and user.deleted_at is not None
            for user in self.users
        )

    async def get_user_by_username(
        self, username: str, with_deleted: bool = False
    ) -> UserInDB | None:
        return next(
            (
                user
                for user in self.users
                if user.username == username
                and (with_deleted or user.deleted_at is None)
            ),
            None,
        )

    async def add(self, data: UserAdd) -> UserInDB:
        self.created.append(data)
        user = UserInDB(
            id=uuid4(), tenant=self.tenant, **data.model_dump(exclude={"roles", "id"})
        )
        self.users.append(user)
        return user


class TenantsInMemory:
    def __init__(self, tenant: TenantInDB):
        self.tenant = tenant

    async def get(self, tenant_id: UUID) -> TenantInDB | None:
        return self.tenant if self.tenant.id == tenant_id else None


class ValidatedToken:
    def __init__(self, claims: dict[str, object]):
        self.claims = claims

    def get_payload_from_openid_jwt(self, **kwargs: object) -> dict[str, object]:
        return self.claims

    def create_access_token_for_user(self, user: UserInDB) -> str:
        return str(user.id)


class AuditLog:
    def __init__(self):
        self.events: list[dict[str, object]] = []

    async def log(self, **event: object) -> None:
        self.events.append(event)


@pytest.fixture
def tenant() -> TenantInDB:
    return TEST_TENANT.model_copy(
        update={
            "id": uuid4(),
            "provisioning": True,
            "state": TenantState.ACTIVE,
            "default_role_id": uuid4(),
        }
    )


@pytest.fixture(params=["federation", "global-oidc"])
def entrypoint(request: pytest.FixtureRequest) -> str:
    return request.param


async def sign_in(
    monkeypatch: pytest.MonkeyPatch,
    tenant: TenantInDB,
    users: UsersInMemory,
    claims: dict[str, object],
    domains: list[str],
    entrypoint: str,
) -> tuple[UserInDB, bool, AuditLog]:
    audit = AuditLog()
    service = UserService(
        user_repo=users,
        tenant_repo=TenantsInMemory(tenant),
        auth_service=ValidatedToken(claims),
        audit_service=audit,
        api_key_auth_resolver=None,
        api_key_v2_repo=None,
        settings_repo=None,
        info_blob_repo=None,
    )
    if entrypoint == "federation":
        user, created = await service.resolve_federated_user(
            identity=FederatedIdentity.from_claims(claims),
            tenant_id=tenant.id,
            allowed_domains=domains,
            correlation_id="admission-test",
        )
    else:
        from eneo.users import user_service

        monkeypatch.setattr(
            user_service,
            "get_settings",
            lambda: SimpleNamespace(
                oidc_client_id="client",
                oidc_tenant_id=str(tenant.id),
                oidc_allowed_domains=domains,
            ),
        )
        token, created, user = await service.login_with_mobilityguard(
            id_token="validated-id-token",
            access_token="access-token",
            key=SimpleNamespace(key="signing-key"),
            signing_algos=["RS256"],
            correlation_id="admission-test",
        )
        assert token == AccessToken(access_token=str(user.id), token_type="bearer")
    return user, created, audit


def existing_user(tenant: TenantInDB, **updates: object) -> UserInDB:
    return TEST_USER.model_copy(
        update={
            "id": uuid4(),
            "email": "user@example.com",
            "tenant_id": tenant.id,
            "tenant": tenant,
            "state": UserState.ACTIVE,
            "deleted_at": None,
            **updates,
        }
    )


CLAIMS: dict[str, object] = {
    "sub": "subject",
    "email": "user@example.com",
    "email_verified": True,
}


async def test_jit_creates_member_with_default_role_and_audit(
    monkeypatch, tenant, entrypoint
):
    users = UsersInMemory(tenant)
    user, created, audit = await sign_in(
        monkeypatch, tenant, users, CLAIMS, ["Example.COM"], entrypoint
    )
    assert created is True
    assert user.tenant_id == tenant.id
    assert user.state == UserState.ACTIVE
    assert user.email == "user@example.com"
    assert user.email_verified is True
    assert len(users.created) == 1
    assert [role.id for role in users.created[0].roles] == [tenant.default_role_id]
    assert len(audit.events) == 1
    assert audit.events[0]["tenant_id"] == tenant.id
    assert audit.events[0]["entity_id"] == user.id


@pytest.mark.parametrize("domains", [[], ["outside.example"]])
async def test_jit_rejects_empty_or_wrong_domain(
    monkeypatch, tenant, entrypoint, domains
):
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied):
        await sign_in(monkeypatch, tenant, users, CLAIMS, domains, entrypoint)
    assert users.created == []


async def test_distinct_international_domains_do_not_alias(
    monkeypatch, tenant, entrypoint
):
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied, match="is not allowed"):
        await sign_in(
            monkeypatch,
            tenant,
            users,
            {**CLAIMS, "email": "user@faß.de"},
            ["fass.de"],
            entrypoint,
        )
    assert users.created == []


@pytest.mark.parametrize("email", ["user@bücher.de", "user@xn--bcher-kva.de"])
@pytest.mark.parametrize("existing", [False, True])
async def test_international_domains_match_unicode_and_punycode(
    monkeypatch, tenant, entrypoint, email, existing
):
    member = existing_user(tenant, email="user@bücher.de") if existing else None
    users = UsersInMemory(tenant, [member] if member else [])
    user, created, _ = await sign_in(
        monkeypatch,
        tenant,
        users,
        {**CLAIMS, "email": email},
        ["xn--bcher-kva.de"],
        entrypoint,
    )
    assert user.email == "user@bücher.de"
    assert created is (not existing)
    if member:
        assert user.id == member.id
        assert users.created == []


async def test_invalid_domain_configuration_fails_closed(
    monkeypatch, tenant, entrypoint
):
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied, match="domains are invalid"):
        await sign_in(
            monkeypatch, tenant, users, CLAIMS, ["invalid domain"], entrypoint
        )
    assert users.created == []


@pytest.mark.parametrize("verified", [None, False, "true", "false", 1, 0])
async def test_jit_requires_boolean_true_verification(
    monkeypatch, tenant, entrypoint, verified
):
    claims = {**CLAIMS, "email_verified": verified}
    if verified is None:
        claims.pop("email_verified")
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied, match="verified email"):
        await sign_in(monkeypatch, tenant, users, claims, ["example.com"], entrypoint)
    assert users.created == []


async def test_provisioning_false_blocks_new_accounts_in_both_paths(
    monkeypatch, tenant, entrypoint
):
    tenant.provisioning = False
    users = UsersInMemory(tenant)
    with pytest.raises(
        FederatedLoginDenied, match="Provision the account through SCIM"
    ):
        await sign_in(monkeypatch, tenant, users, CLAIMS, ["example.com"], entrypoint)
    assert users.created == []


@pytest.mark.parametrize("verified", [None, False])
async def test_existing_scim_member_can_sign_in_without_jit_requirements(
    monkeypatch, tenant, entrypoint, verified
):
    tenant.provisioning = False
    member = existing_user(tenant)
    users = UsersInMemory(tenant, [member])
    claims = {"sub": "subject", "email": member.email, "email_verified": verified}
    user, created, audit = await sign_in(
        monkeypatch, tenant, users, claims, [], entrypoint
    )
    assert user.id == member.id
    assert created is False
    assert users.created == []
    assert audit.events == []


@pytest.mark.parametrize("state", [UserState.INACTIVE, UserState.DELETED])
async def test_inactive_or_removed_member_cannot_be_recreated(
    monkeypatch, tenant, entrypoint, state
):
    member = existing_user(
        tenant,
        state=state,
        deleted_at=(datetime.now(timezone.utc) if state == UserState.DELETED else None),
    )
    users = UsersInMemory(tenant, [member])
    with pytest.raises(FederatedLoginDenied, match="inactive or has been removed"):
        await sign_in(monkeypatch, tenant, users, CLAIMS, ["example.com"], entrypoint)
    assert users.created == []
    assert member.state == state


async def test_scim_reactivation_allows_same_account_to_sign_in(
    monkeypatch, tenant, entrypoint
):
    member = existing_user(
        tenant, state=UserState.DELETED, deleted_at=datetime.now(timezone.utc)
    )
    users = UsersInMemory(tenant, [member])
    with pytest.raises(FederatedLoginDenied):
        await sign_in(monkeypatch, tenant, users, CLAIMS, [], entrypoint)
    # SCIM/admin restores the original row; OIDC must reuse it.
    member.state = UserState.ACTIVE
    member.deleted_at = None
    user, created, _ = await sign_in(monkeypatch, tenant, users, CLAIMS, [], entrypoint)
    assert user.id == member.id
    assert created is False
    assert users.created == []


async def test_existing_member_in_other_tenant_is_denied(
    monkeypatch, tenant, entrypoint
):
    member = existing_user(tenant, tenant_id=uuid4())
    users = UsersInMemory(tenant, [member])
    with pytest.raises(FederatedLoginDenied, match="Access denied"):
        await sign_in(monkeypatch, tenant, users, CLAIMS, [], entrypoint)
    assert users.created == []


@pytest.mark.parametrize("state", [TenantState.SUSPENDED])
async def test_inactive_tenant_cannot_admit_users(
    monkeypatch, tenant, entrypoint, state
):
    tenant.state = state
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied, match="Tenant is not active"):
        await sign_in(monkeypatch, tenant, users, CLAIMS, ["example.com"], entrypoint)
    assert users.created == []


@pytest.mark.parametrize("mapped_email", ["user@example.com", "someone@example.com"])
def test_verification_must_cover_the_selected_email(mapped_email):
    identity = FederatedIdentity.from_claims(
        {**CLAIMS, "mail": mapped_email}, email_claim="mail"
    )
    assert identity.email_verified is (mapped_email == CLAIMS["email"])


@pytest.mark.parametrize("email", [None, 123, "", "invalid", "user@", "@example.com"])
def test_invalid_email_is_rejected_before_account_admission(email):
    with pytest.raises(ValueError):
        FederatedIdentity.from_claims({"email": email, "email_verified": True})


def test_global_oidc_domain_configuration_is_resolved(test_settings, monkeypatch):
    monkeypatch.setenv("OIDC_ALLOWED_DOMAINS", '["example.com"]')
    settings = Settings(
        _env_file=None,
        **test_settings.model_dump(exclude={"oidc_allowed_domains"}),
    )
    settings.oidc_discovery_endpoint = "https://idp.example.com/discovery"
    settings.oidc_client_secret = "secret"
    assert settings.oidc_allowed_domains == ["example.com"]
    config = CredentialResolver(settings=settings).get_federation_config()
    assert config["allowed_domains"] == ["example.com"]


@pytest.mark.parametrize(
    "removed, same_tenant", [(True, True), (True, False), (False, True)]
)
async def test_removed_account_lookup_executes_scoped_case_insensitive_sql(
    tenant, removed, same_tenant
):
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "CREATE TABLE users (email TEXT, tenant_id CHAR(32), deleted_at TEXT)"
                )
            )
            owner = tenant.id if same_tenant else uuid4()
            for _ in range(2):
                connection.execute(
                    sa.text(
                        "INSERT INTO users VALUES (:email, :tenant_id, :deleted_at)"
                    ),
                    {
                        "email": "User@Example.COM",
                        "tenant_id": owner.hex,
                        "deleted_at": "2026-09-30" if removed else None,
                    },
                )
            # Run the real repository query; no PostgreSQL server is needed for
            # this existence/read contract, including duplicate historical rows.
            session = AsyncMock()
            session.scalar.side_effect = connection.scalar
            repository = UsersRepository(session)
            found = await repository.has_removed_user_by_email(
                "user@example.com", tenant.id
            )
            assert found is (removed and same_tenant)
            assert (
                await repository.has_removed_user_by_email(
                    "other@example.com", tenant.id
                )
                is False
            )
    finally:
        engine.dispose()
