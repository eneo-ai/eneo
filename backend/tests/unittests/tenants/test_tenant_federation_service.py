"""Pure rules of TenantFederationService: revision, audit diff, the tenant-admin
request and the read model that never carries the secret."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from eneo.main.config import Settings
from eneo.tenants.masking import looks_masked
from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.tenants.tenant_federation_service import (
    PatchFederationRequest,
    SetFederationRequest,
    TenantAdminFederationPatch,
    _build_full_federation_config,
    _merge_federation_config,
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

    def test_a_legacy_row_hashes_like_the_tenant_loaded_from_it(self):
        raw = _config(
            redirect_path="/login/callback/",
            canonical_public_origin="https://Org.Eneo.test/",
        )

        loaded = _tenant(dict(raw)).federation_config

        assert loaded["redirect_path"] == "/login/callback"
        assert federation_revision(raw) == federation_revision(loaded)

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
            "signing_algorithms",
            "email_verified_claims",
            "tenant_id",
        ],
    )
    def test_refuses_operator_owned_fields(self, field: str):
        with pytest.raises(ValidationError):
            TenantAdminFederationPatch.model_validate({"revision": "r", field: "x"})

    @pytest.mark.parametrize(
        "field",
        ["provider", "client_id", "client_secret", "allowed_domains", "subject_claim"],
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

    @pytest.mark.parametrize("secret", ["", "short", "1234567"])
    def test_refuses_a_short_secret(self, secret: str):
        with pytest.raises(ValidationError):
            TenantAdminFederationPatch.model_validate(
                {"revision": "r", "client_secret": secret}
            )

    @pytest.mark.parametrize("masked", ["...cret", "sk-...abcd", "***", "••••"])
    def test_lets_a_masked_value_through_to_be_refused_as_such(self, masked: str):
        # The service answers 400 federation_secret_looks_masked, not a 422
        # about its length.
        patch = TenantAdminFederationPatch.model_validate(
            {"revision": "r", "client_secret": masked}
        )
        assert patch.client_secret == masked

    def test_the_schema_offers_omission_not_null(self):
        properties = TenantAdminFederationPatch.model_json_schema()["properties"]

        for field in ("provider", "client_id", "client_secret", "allowed_domains"):
            assert "anyOf" not in properties[field], field
            assert properties[field]["type"] in ("string", "array"), field
        assert properties["client_id"]["minLength"] == 1


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


class TestOperatorProviderKeys:
    """The operator may name the provider's signing algorithms and the claims
    that say an email is verified; absent keys keep the built-in defaults."""

    BODY = {
        "provider": "example",
        "discovery_endpoint": "https://idp.example/.well-known/openid-configuration",
        "client_id": "eneo-client",
        "client_secret": "operator-secret",
    }

    def _put(self, **keys: object) -> dict[str, object]:
        return _build_full_federation_config(
            SetFederationRequest.model_validate({**self.BODY, **keys}),
            encrypted_secret=CIPHERTEXT,
        )

    def test_absent_keys_are_not_stored(self):
        config = self._put()

        assert "signing_algorithms" not in config
        assert "email_verified_claims" not in config

    def test_given_keys_are_stored(self):
        config = self._put(
            signing_algorithms=["ES256", "RS256"],
            email_verified_claims=["email_verified"],
        )

        assert config["signing_algorithms"] == ["ES256", "RS256"]
        assert config["email_verified_claims"] == ["email_verified"]

    @pytest.mark.parametrize(
        "keys",
        [
            {"signing_algorithms": []},
            {"signing_algorithms": ["HS256"]},
            {"signing_algorithms": ["none"]},
            {"signing_algorithms": ["RS256", "HS256"]},
            {"email_verified_claims": []},
            {"email_verified_claims": [""]},
        ],
    )
    def test_refuses_keys_that_weaken_or_empty_the_check(self, keys: dict[str, object]):
        with pytest.raises(ValidationError):
            SetFederationRequest.model_validate({**self.BODY, **keys})

    def test_patch_sets_and_null_clears(self):
        stored = _config(signing_algorithms=["RS256"])

        def patch(**keys: object) -> dict[str, object]:
            request = PatchFederationRequest.model_validate(keys)
            return _merge_federation_config(
                stored,
                request.model_dump(exclude_unset=True),
                encrypted_secret=None,
            )

        assert patch(email_verified_claims=["xms_edov"])["email_verified_claims"] == [
            "xms_edov"
        ]
        assert "signing_algorithms" not in patch(signing_algorithms=None)
        assert patch(client_id="other")["signing_algorithms"] == ["RS256"]


class TestSubjectClaim:
    """Both doors may name the claim an account is bound to; it is stored as
    claims_mapping.subject and is never the email claim."""

    BODY = TestOperatorProviderKeys.BODY

    def _put(self, **keys: object) -> dict[str, object]:
        return _build_full_federation_config(
            SetFederationRequest.model_validate({**self.BODY, **keys}),
            encrypted_secret=CIPHERTEXT,
        )

    @staticmethod
    def _patch(stored: dict[str, object], request: object) -> dict[str, object]:
        assert isinstance(request, (PatchFederationRequest, TenantAdminFederationPatch))
        return _merge_federation_config(
            stored,
            request.model_dump(exclude_unset=True, exclude={"revision"}),
            encrypted_secret=None,
        )

    def test_put_stores_the_default_or_the_given_claim(self):
        assert self._put()["claims_mapping"] == {
            "email": "email",
            "subject": "sub",
            "username": "sub",
            "name": "name",
        }
        claims = self._put(subject_claim=" oid ")["claims_mapping"]
        assert isinstance(claims, dict)
        assert claims["subject"] == "oid"
        assert claims["email"] == "email"

    def test_put_refuses_the_email_claim(self):
        with pytest.raises(HTTPException) as refused:
            self._put(subject_claim="email")
        assert refused.value.status_code == 422

    @pytest.mark.parametrize(
        "model", [PatchFederationRequest, TenantAdminFederationPatch]
    )
    def test_patch_changes_only_the_subject_and_keeps_the_mapping(self, model):
        stored = _config()

        merged = self._patch(
            stored, model.model_validate({"revision": "r", "subject_claim": "oid"})
        )

        assert merged["claims_mapping"] == {
            "email": "upn",
            "subject": "oid",
            "username": "sub",
            "name": "name",
        }
        assert stored["claims_mapping"] == {
            "email": "upn",
            "username": "sub",
            "name": "name",
        }

    @pytest.mark.parametrize(
        "model", [PatchFederationRequest, TenantAdminFederationPatch]
    )
    def test_patch_without_the_claim_keeps_the_stored_one(self, model):
        stored = _config(
            claims_mapping={"email": "upn", "subject": "oid", "name": "name"}
        )

        merged = self._patch(
            stored, model.model_validate({"revision": "r", "client_id": "other"})
        )

        assert merged["claims_mapping"] == stored["claims_mapping"]

    @pytest.mark.parametrize(
        "model", [PatchFederationRequest, TenantAdminFederationPatch]
    )
    def test_patch_refuses_the_stored_email_claim(self, model):
        with pytest.raises(HTTPException) as refused:
            self._patch(
                _config(),
                model.model_validate({"revision": "r", "subject_claim": "upn"}),
            )
        assert refused.value.status_code == 422

    @pytest.mark.parametrize("claim", ["", "   "])
    def test_put_refuses_an_empty_claim(self, claim: str):
        with pytest.raises(ValidationError):
            SetFederationRequest.model_validate({**self.BODY, "subject_claim": claim})

    @pytest.mark.parametrize("claim", ["", "   ", None])
    def test_the_operator_patch_refuses_an_empty_or_null_claim(self, claim):
        with pytest.raises(ValidationError):
            PatchFederationRequest.model_validate({"subject_claim": claim})

    @pytest.mark.parametrize("claim", ["", "   "])
    def test_the_admin_door_refuses_an_empty_claim(self, claim: str):
        with pytest.raises(ValidationError):
            TenantAdminFederationPatch.model_validate(
                {"revision": "r", "subject_claim": claim}
            )

    def test_the_admin_view_shows_the_effective_claim(self, settings: Settings):
        assert build_admin_view(_tenant(_config()), settings).subject_claim == "sub"
        configured = _config(claims_mapping={"email": "upn", "subject": "oid"})
        assert build_admin_view(_tenant(configured), settings).subject_claim == "oid"
