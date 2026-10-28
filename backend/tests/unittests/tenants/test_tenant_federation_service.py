"""Pure rules of TenantFederationService: revision, audit diff, the tenant-admin
request and the read model that never carries the secret."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.main.config import Settings
from eneo.tenants.masking import looks_masked
from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.tenants.tenant_federation_service import (
    TenantAdminFederationPatch,
    build_admin_view,
    federation_changes,
    federation_revision,
)

CIPHERTEXT = "enc:fernet:v1:gAAAAABlongciphertextvalue"
ENCRYPTED_AT = "2026-10-01T08:00:00+00:00"


def _config(**overrides: object) -> dict[str, object]:
    return {
        "provider": "entra",
        "discovery_endpoint": "https://idp.example/.well-known/openid-configuration",
        "issuer": "https://idp.example",
        "authorization_endpoint": "https://idp.example/authorize",
        "token_endpoint": "https://idp.example/token",
        "jwks_uri": "https://idp.example/jwks",
        "client_id": "eneo-client",
        "client_secret": CIPHERTEXT,
        "scopes": ["openid", "email"],
        "claims_mapping": {"email": "upn", "username": "sub", "name": "name"},
        "allowed_domains": ["example.se"],
        "token_endpoint_auth_method": "client_secret_basic",
        "canonical_public_origin": "https://org.eneo.test",
        "encrypted_at": ENCRYPTED_AT,
        **overrides,
    }


def _tenant(config: dict[str, object]) -> TenantInDB:
    now = datetime.now(timezone.utc)
    return TenantInDB(
        id=uuid4(),
        name="org",
        quota_limit=0,
        state=TenantState.ACTIVE,
        federation_config=config,
        created_at=now,
        updated_at=now,
    )


class TestRevision:
    def test_absent_without_a_config(self):
        assert federation_revision({}) is None

    def test_ignores_key_order(self):
        config = _config()
        assert federation_revision(config) == federation_revision(
            dict(reversed(list(config.items())))
        )

    def test_never_depends_on_the_secret_value(self):
        # Replacing the secret also stamps encrypted_at, which moves the revision.
        assert federation_revision(_config()) == federation_revision(
            _config(client_secret="enc:fernet:v1:other")
        )
        assert federation_revision(_config()) != federation_revision(
            _config(encrypted_at="2026-10-02T08:00:00+00:00")
        )

    def test_moves_with_any_setting(self):
        assert federation_revision(_config()) != federation_revision(
            _config(client_id="other")
        )


class TestChanges:
    def test_names_each_changed_field_from_what_to_what(self):
        old = _config()
        new = _config(client_id="next", allowed_domains=["example.se", "b.se"])

        assert federation_changes(old, new, secret_replaced=False) == {
            "client_id": {"old": "eneo-client", "new": "next"},
            "allowed_domains": {"old": ["example.se"], "new": ["example.se", "b.se"]},
        }

    def test_records_a_replaced_secret_without_any_value(self):
        new = _config(client_secret="enc:fernet:v1:new", encrypted_at="later")

        changes = federation_changes(_config(), new, secret_replaced=True)

        assert changes == {"client_secret": {"replaced": True}}

    def test_a_deleted_config_lists_what_was_removed(self):
        changes = federation_changes(_config(), {}, secret_replaced=False)

        assert changes["client_id"] == {"old": "eneo-client", "new": None}
        assert "client_secret" not in changes
        assert CIPHERTEXT not in str(changes)


class TestTenantAdminPatch:
    def test_requires_the_revision(self):
        with pytest.raises(ValidationError):
            TenantAdminFederationPatch.model_validate({"client_id": "x"})

    @pytest.mark.parametrize(
        "field",
        [
            "discovery_endpoint",
            "issuer",
            "token_endpoint",
            "jwks_uri",
            "canonical_public_origin",
            "redirect_path",
            "additional_redirect_uris",
            "scopes",
            "email_claim",
            "claims_mapping",
            "token_endpoint_auth_method",
            "tenant_id",
        ],
    )
    def test_refuses_operator_owned_fields(self, field: str):
        with pytest.raises(ValidationError):
            TenantAdminFederationPatch.model_validate({"revision": "r", field: "x"})

    @pytest.mark.parametrize(
        "field", ["provider", "client_id", "client_secret", "allowed_domains"]
    )
    def test_refuses_null(self, field: str):
        with pytest.raises(ValidationError):
            TenantAdminFederationPatch.model_validate({"revision": "r", field: None})

    def test_refuses_an_empty_client_id(self):
        with pytest.raises(ValidationError):
            TenantAdminFederationPatch.model_validate(
                {"revision": "r", "client_id": "  "}
            )

    def test_normalises_domains_and_refuses_invalid_ones(self):
        patch = TenantAdminFederationPatch.model_validate(
            {"revision": "r", "allowed_domains": ["Example.SE"]}
        )
        assert patch.allowed_domains == ["example.se"]
        with pytest.raises(ValidationError):
            TenantAdminFederationPatch.model_validate(
                {"revision": "r", "allowed_domains": ["not a domain"]}
            )

    def test_trims_the_secret(self):
        patch = TenantAdminFederationPatch.model_validate(
            {"revision": "r", "client_secret": "  a-new-secret  "}
        )
        assert patch.client_secret == "a-new-secret"


@pytest.mark.parametrize(
    ("value", "masked"),
    [
        ("...cret", True),
        ("sk-...abcd", True),
        ("********", True),
        ("••••••••", True),
        ("a-real-secret", False),
        ("abc...def", False),
    ],
)
def test_looks_masked(value: str, masked: bool):
    assert looks_masked(value) is masked


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"federation_enabled": True})


class TestAdminView:
    def test_shows_the_settings_and_never_the_secret(self, settings: Settings):
        view = build_admin_view(_tenant(_config()), settings)

        assert view.configured is True
        assert view.client_secret_set is True
        assert view.client_secret_updated_at == datetime.fromisoformat(ENCRYPTED_AT)
        assert view.encryption_status == "encrypted"
        assert view.client_id == "eneo-client"
        assert view.scopes == ["openid", "email"]
        assert view.token_endpoint_auth_method == "client_secret_basic"
        assert view.redirect_uris == ["https://org.eneo.test/login/callback"]
        assert view.redirect_uris_problem is None
        assert view.revision == federation_revision(_config())
        dumped = view.model_dump_json()
        assert 'client_secret"' not in dumped
        assert CIPHERTEXT not in dumped
        assert "..." not in dumped

    def test_unresolvable_redirect_uris_are_named_not_raised(self, settings: Settings):
        config = _config()
        del config["canonical_public_origin"]

        view = build_admin_view(
            _tenant(config), settings.model_copy(update={"public_origin": None})
        )

        assert view.redirect_uris == []
        assert view.redirect_uris_problem == "unresolvable"

    @pytest.mark.parametrize(
        "config", [{}, {"canonical_public_origin": "https://org.eneo.test"}]
    )
    def test_not_configured_until_the_operator_registers_an_idp(
        self, config: dict[str, object], settings: Settings
    ):
        view = build_admin_view(_tenant(config), settings)

        assert view.configured is False
        assert view.revision is None
        assert view.client_secret_set is False
