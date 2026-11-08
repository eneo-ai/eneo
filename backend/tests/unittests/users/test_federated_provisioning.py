"""Behavior contracts for membership admission through both OIDC login paths."""

from collections.abc import Sequence
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.domain.action_types import ActionType
from eneo.authentication.auth_models import FederatedIdentity
from eneo.main.config import Settings
from eneo.main.exceptions import FederatedLoginDenied
from eneo.settings.credential_resolver import CredentialResolver
from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.users.user import UserAdd, UserInDB, UserState
from eneo.users.user_repo import UsersRepository
from eneo.users.user_service import UserService
from tests.fixtures import TEST_TENANT, TEST_USER
from tests.identity_bindings_in_memory import IdentityBindingsInMemory

ISSUER = "https://idp.example.org"


def identity_of(claims: dict[str, object], **mapping: str) -> FederatedIdentity:
    return FederatedIdentity.from_claims(
        claims, issuer=ISSUER, audience="client", **mapping
    )


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

    async def get_users_by_email(self, email: str, *, limit: int) -> list[UserInDB]:
        return [
            user
            for user in self.users
            if user.email.lower() == email.lower() and user.deleted_at is None
        ][:limit]

    async def get_user_by_id(
        self, id: UUID, with_deleted: bool = False
    ) -> UserInDB | None:
        return next(
            (
                user
                for user in self.users
                if user.id == id and (with_deleted or user.deleted_at is None)
            ),
            None,
        )

    async def get_user_by_id_for_update(self, id: UUID) -> UserInDB | None:
        return await self.get_user_by_id(id)

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

    async def log_async(self, **event: object) -> None:
        self.events.append(event)

    def of(self, action: ActionType) -> list[dict[str, object]]:
        return [event for event in self.events if event["action"] == action]


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


async def sign_in(
    tenant: TenantInDB,
    users: UsersInMemory,
    claims: dict[str, object],
    domains: list[str],
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
        identity_binding_repo=IdentityBindingsInMemory(),
    )
    user, created = await service.resolve_federated_user(
        identity=identity_of(claims),
        tenant_id=tenant.id,
        allowed_domains=domains,
        correlation_id="admission-test",
    )
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
    "iss": ISSUER,
    "sub": "subject",
    "email": "user@example.com",
    "email_verified": True,
}


async def test_jit_creates_member_with_default_role_and_audit(
    tenant,
):
    users = UsersInMemory(tenant)
    user, created, audit = await sign_in(
        tenant,
        users,
        CLAIMS,
        ["Example.COM"],
    )
    assert created is True
    assert user.tenant_id == tenant.id
    assert user.state == UserState.ACTIVE
    assert user.email == "user@example.com"
    assert user.email_verified is True
    assert len(users.created) == 1
    assert [role.id for role in users.created[0].roles] == [tenant.default_role_id]
    [created_event] = audit.of(ActionType.USER_CREATED)
    assert created_event["tenant_id"] == tenant.id
    assert created_event["entity_id"] == user.id
    [bound] = audit.of(ActionType.IDENTITY_BOUND)
    assert (bound["entity_id"], bound["metadata"]["method"]) == (user.id, "jit")


@pytest.mark.parametrize("domains", [[], ["outside.example"]])
async def test_jit_rejects_empty_or_wrong_domain(tenant, domains):
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied):
        await sign_in(tenant, users, CLAIMS, domains)
    assert users.created == []


async def test_distinct_international_domains_do_not_alias(
    tenant,
):
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied, match="is not allowed"):
        await sign_in(
            tenant,
            users,
            {**CLAIMS, "email": "user@faß.de"},
            ["fass.de"],
        )
    assert users.created == []


@pytest.mark.parametrize("email", ["user@bücher.de", "user@xn--bcher-kva.de"])
@pytest.mark.parametrize("existing", [False, True])
async def test_international_domains_match_unicode_and_punycode(
    tenant, email, existing
):
    member = existing_user(tenant, email="user@bücher.de") if existing else None
    users = UsersInMemory(tenant, [member] if member else [])
    user, created, _ = await sign_in(
        tenant,
        users,
        {**CLAIMS, "email": email},
        ["xn--bcher-kva.de"],
    )
    assert user.email == "user@bücher.de"
    assert created is (not existing)
    if member:
        assert user.id == member.id
        assert users.created == []


async def test_invalid_domain_configuration_fails_closed(
    tenant,
):
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied, match="domains are invalid"):
        await sign_in(
            tenant,
            users,
            CLAIMS,
            ["invalid domain"],
        )
    assert users.created == []


@pytest.mark.parametrize("verified", ["true", "TRUE", " True ", "1", 1])
async def test_jit_accepts_text_forms_of_a_positive_verification(tenant, verified):
    users = UsersInMemory(tenant)
    user, created, _ = await sign_in(
        tenant,
        users,
        {**CLAIMS, "email_verified": verified},
        ["example.com"],
    )
    assert created is True
    assert user.email_verified is True


@pytest.mark.parametrize("domain_verified", [True, "true", "1", 1])
async def test_jit_accepts_entra_domain_owner_verification(tenant, domain_verified):
    """Entra ID omits email_verified for organisational accounts; its optional
    xms_edov claim is the equivalent signal for the standard email."""
    claims = {**CLAIMS, "xms_edov": domain_verified}
    claims.pop("email_verified")
    users = UsersInMemory(tenant)
    user, created, _ = await sign_in(
        tenant,
        users,
        claims,
        ["example.com"],
    )
    assert created is True
    assert user.email_verified is True


@pytest.mark.parametrize("domain_verified", [False, "false", "0", 0, "", None])
async def test_jit_rejects_a_negative_or_missing_entra_domain_verification(
    tenant, domain_verified
):
    claims = {**CLAIMS, "xms_edov": domain_verified}
    claims.pop("email_verified")
    if domain_verified is None:
        claims.pop("xms_edov")
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied, match="verified email"):
        await sign_in(tenant, users, claims, ["example.com"])
    assert users.created == []


def test_entra_domain_verification_does_not_override_an_explicit_negative():
    with pytest.raises(ValueError, match="not verified"):
        identity_of({**CLAIMS, "email_verified": False, "xms_edov": True})


@pytest.mark.parametrize("email_verified", ["false", "0", 0, "", "yes", 2, "true1"])
async def test_entra_domain_verification_is_only_a_fallback_for_a_missing_claim(
    tenant, email_verified
):
    """A sent email_verified keeps its own verdict; xms_edov never overrides
    a negative or unrecognised value, only fills in for an absent one."""
    claims = {**CLAIMS, "email_verified": email_verified, "xms_edov": True}
    assert identity_of(claims).email_verified is False
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied, match="verified email"):
        await sign_in(tenant, users, claims, ["example.com"])
    assert users.created == []


def test_entra_domain_verification_fills_in_for_a_null_claim():
    identity = identity_of({**CLAIMS, "email_verified": None, "xms_edov": True})
    assert identity.email_verified is True


@pytest.mark.parametrize(
    "verified", [None, "false", "0", 0, 2, "yes", "", "true1", 1.0, ["true"]]
)
async def test_jit_requires_a_positive_verification(tenant, verified):
    claims = {**CLAIMS, "email_verified": verified}
    if verified is None:
        claims.pop("email_verified")
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied, match="verified email"):
        await sign_in(tenant, users, claims, ["example.com"])
    assert users.created == []


async def test_provisioning_false_blocks_new_accounts_in_both_paths(
    tenant,
):
    tenant.provisioning = False
    users = UsersInMemory(tenant)
    with pytest.raises(
        FederatedLoginDenied, match="Provision the account through SCIM"
    ):
        await sign_in(tenant, users, CLAIMS, ["example.com"])
    assert users.created == []


@pytest.mark.parametrize("verified", [None, True])
async def test_existing_scim_member_can_sign_in_without_jit_requirements(
    tenant, verified
):
    tenant.provisioning = False
    member = existing_user(tenant)
    users = UsersInMemory(tenant, [member])
    claims = {
        "iss": ISSUER,
        "sub": "subject",
        "email": member.email,
        "email_verified": verified,
    }
    user, created, audit = await sign_in(
        tenant,
        users,
        claims,
        [],
    )
    assert user.id == member.id
    assert created is False
    assert users.created == []
    assert audit.of(ActionType.USER_CREATED) == []


@pytest.mark.parametrize("state", [UserState.INACTIVE, UserState.DELETED])
async def test_inactive_or_removed_member_cannot_be_recreated(tenant, state):
    member = existing_user(
        tenant,
        state=state,
        deleted_at=(datetime.now(timezone.utc) if state == UserState.DELETED else None),
    )
    users = UsersInMemory(tenant, [member])
    with pytest.raises(FederatedLoginDenied, match="inactive or has been removed"):
        await sign_in(tenant, users, CLAIMS, ["example.com"])
    assert users.created == []
    assert member.state == state


async def test_scim_reactivation_allows_same_account_to_sign_in(
    tenant,
):
    member = existing_user(
        tenant, state=UserState.DELETED, deleted_at=datetime.now(timezone.utc)
    )
    users = UsersInMemory(tenant, [member])
    with pytest.raises(FederatedLoginDenied):
        await sign_in(tenant, users, CLAIMS, [])
    # SCIM/admin restores the original row; OIDC must reuse it.
    member.state = UserState.ACTIVE
    member.deleted_at = None
    user, created, _ = await sign_in(tenant, users, CLAIMS, [])
    assert user.id == member.id
    assert created is False
    assert users.created == []


async def test_existing_member_in_other_tenant_is_denied(
    tenant,
):
    member = existing_user(tenant, tenant_id=uuid4())
    users = UsersInMemory(tenant, [member])
    with pytest.raises(FederatedLoginDenied, match="Access denied"):
        await sign_in(tenant, users, CLAIMS, [])
    assert users.created == []


@pytest.mark.parametrize("state", [TenantState.SUSPENDED])
async def test_inactive_tenant_cannot_admit_users(tenant, state):
    tenant.state = state
    users = UsersInMemory(tenant)
    with pytest.raises(FederatedLoginDenied, match="Tenant is not active"):
        await sign_in(tenant, users, CLAIMS, ["example.com"])
    assert users.created == []


@pytest.mark.parametrize("verification_claim", ["email_verified", "xms_edov"])
@pytest.mark.parametrize("verified", [True, "true"])
@pytest.mark.parametrize("mapped_email", ["user@example.com", "someone@example.com"])
def test_verification_must_cover_the_selected_email(
    mapped_email, verified, verification_claim
):
    claims = {**CLAIMS, "mail": mapped_email}
    claims.pop("email_verified")
    claims[verification_claim] = verified
    identity = identity_of(claims, email_claim="mail")
    assert identity.email_verified is (mapped_email == CLAIMS["email"])


@pytest.mark.parametrize("existing", [False, True])
async def test_explicitly_unverified_email_is_rejected_before_account_admission(
    tenant, existing
):
    member = existing_user(tenant) if existing else None
    users = UsersInMemory(tenant, [member] if member else [])
    claims = {**CLAIMS, "email_verified": False}
    with pytest.raises(ValueError):
        await sign_in(tenant, users, claims, ["example.com"])
    assert users.created == []
    if member:
        assert member.state == UserState.ACTIVE


def test_custom_directory_claim_is_not_rejected_by_unrelated_email_verification():
    identity = identity_of(
        {
            "sub": "subject",
            "email": "unverified@external.example",
            "email_verified": False,
            "upn": "employee@municipality.example",
        },
        email_claim="upn",
    )
    assert identity.email == "employee@municipality.example"
    assert identity.email_verified is False


@pytest.mark.parametrize("email", [None, 123, "", "invalid", "user@", "@example.com"])
def test_invalid_email_is_rejected_before_account_admission(email):
    with pytest.raises(ValueError):
        identity_of({"email": email, "email_verified": True})


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
