"""What Eneo sends to an OpenID provider and what it accepts back.

Every login runs against the fake provider: the authorization request always
carries state, nonce and PKCE S256; the sign-in transaction is single use and
lives only in Redis; the ID token must pass every check, and a failed check is
never retried through a weaker path.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest

from eneo.authentication import federation_router
from eneo.authentication.auth_models import FederatedIdentity
from eneo.authentication.federation_router import CallbackRequest
from eneo.authentication.oidc import profile as oidc_profile
from eneo.authentication.oidc import transaction as oidc_transaction
from eneo.authentication.oidc.authorization import build_authorization_request
from eneo.authentication.oidc.errors import (
    OidcLoginUnavailableError,
    OidcResponseNotVerifiedError,
    OidcTransactionInvalidError,
)
from eneo.authentication.oidc.profile import (
    OidcProviderError,
    build_profile,
    load_profile,
)
from eneo.authentication.oidc.transaction import (
    OidcTransaction,
    save_transaction,
    take_transaction,
)
from eneo.authentication.oidc.verification import CallbackResponse, verify_response
from eneo.authentication.oidc_resource_server import (
    JWKSFetchError,
    get_federation_signing_key,
)
from eneo.main.exceptions import AuthenticationException
from eneo.users.user_service import UserService
from tests.fake_oidc_provider import DROP, FakeOidcProvider, install
from tests.unit.authentication.test_oidc_login_compatibility import (
    REDIRECT_URI,
    Login,
)
from tests.unittests.authentication.test_federation_router import FakeRedis

NOW = int(time.time())


def _token_posts(provider: FakeOidcProvider) -> int:
    return sum(
        1
        for method, url in provider.requests
        if method == "POST" and url == provider.token_endpoint
    )


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


async def test_every_authorization_request_carries_state_nonce_and_s256(
    monkeypatch,
):
    login = Login(monkeypatch, FakeOidcProvider())

    first = _query((await login.initiate()).authorization_url)
    second = _query((await login.initiate()).authorization_url)

    for query in (first, second):
        assert query["state"][0]
        assert len(query["nonce"][0]) >= 32
        assert query["code_challenge_method"] == ["S256"]
        assert len(query["code_challenge"][0]) == 43
    assert first["nonce"] != second["nonce"]
    assert first["code_challenge"] != second["code_challenge"]
    assert "plain" not in json.dumps([first, second])


async def test_the_verifier_never_leaves_the_server(monkeypatch):
    login = Login(monkeypatch, FakeOidcProvider())

    started = await login.initiate()

    (stored,) = login.redis._store.values()
    verifier = json.loads(stored)["code_verifier"]
    assert verifier not in started.authorization_url
    assert verifier not in started.state


@pytest.mark.parametrize("db_mode", [True, False], ids=["db-mode", "env-mode"])
async def test_a_provider_that_enforces_pkce_signs_in(monkeypatch, db_mode):
    provider = FakeOidcProvider(pkce="enforce")
    login = Login(
        monkeypatch, provider, db_mode=db_mode, existing_email="user@example.com"
    )

    result = await login.sign_in()

    assert login.signed_in_user(result)
    assert _token_posts(provider) == 1


async def test_a_wrong_verifier_is_refused_by_an_enforcing_provider(monkeypatch):
    provider = FakeOidcProvider(pkce="enforce")
    login = Login(monkeypatch, provider)
    started = await login.initiate()
    answer = provider.authorize(started.authorization_url)
    (key,) = login.redis._store
    stored = json.loads(login.redis._store[key])
    login.redis._store[key] = json.dumps({**stored, "code_verifier": "x" * 86})

    with pytest.raises(OidcResponseNotVerifiedError):
        await federation_router.auth_callback(
            CallbackRequest(code=answer.code, state=started.state), login.container
        )

    assert _token_posts(provider) == 1
    assert login.users._created_user is None


async def test_a_provider_that_ignores_pkce_still_signs_in(monkeypatch):
    provider = FakeOidcProvider(pkce="ignore")
    login = Login(monkeypatch, provider)

    await login.sign_in(email="new.person@example.com")

    assert provider.token_requests[0]["code_verifier"]
    assert login.users._created_user is not None


@pytest.mark.parametrize(
    "provider",
    [
        pytest.param(
            FakeOidcProvider(token_claims={"iss": "https://other.example"}),
            id="wrong-iss",
        ),
        pytest.param(FakeOidcProvider(token_claims={"iss": DROP}), id="missing-iss"),
        pytest.param(
            FakeOidcProvider(token_claims={"aud": "another-client"}), id="wrong-aud"
        ),
        pytest.param(
            FakeOidcProvider(token_claims={"azp": "another-client"}), id="wrong-azp"
        ),
        pytest.param(
            FakeOidcProvider(token_claims={"aud": ["eneo-client", "another-client"]}),
            id="several-audiences-without-azp",
        ),
        pytest.param(
            FakeOidcProvider(token_claims={"nonce": "another-nonce"}),
            id="wrong-nonce",
        ),
        pytest.param(
            FakeOidcProvider(token_claims={"nonce": DROP}), id="missing-nonce"
        ),
        pytest.param(
            FakeOidcProvider(token_claims={"nonce": "nonce-åäö"}),
            id="non-ascii-nonce",
        ),
        pytest.param(
            FakeOidcProvider(token_claims={"at_hash": "wrong"}), id="wrong-at-hash"
        ),
        pytest.param(
            FakeOidcProvider(token_claims={"at_hash": ""}), id="empty-at-hash"
        ),
        pytest.param(
            FakeOidcProvider(token_claims={"at_hash": None}), id="null-at-hash"
        ),
        pytest.param(FakeOidcProvider(signing_override="foreign"), id="signature"),
        pytest.param(
            FakeOidcProvider(signing_override="HS256", advertised_algorithms=["RS256"]),
            id="symmetric-algorithm",
        ),
        pytest.param(
            FakeOidcProvider(algorithm="ES256", advertised_algorithms=["RS256"]),
            id="algorithm-not-advertised",
        ),
        pytest.param(
            FakeOidcProvider(
                signing_override="ES256-under-rsa-kid",
                advertised_algorithms=["RS256", "ES256"],
            ),
            id="algorithm-not-fitting-the-key",
        ),
        pytest.param(FakeOidcProvider(token_claims={"exp": NOW - 600}), id="expired"),
        pytest.param(FakeOidcProvider(token_claims={"exp": DROP}), id="missing-exp"),
        pytest.param(FakeOidcProvider(token_claims={"aud": DROP}), id="missing-aud"),
        pytest.param(FakeOidcProvider(token_claims={"iat": DROP}), id="missing-iat"),
        pytest.param(
            FakeOidcProvider(token_claims={"iat": NOW + 600}), id="future-iat"
        ),
        pytest.param(
            FakeOidcProvider(token_claims={"auth_time": NOW + 600}),
            id="future-auth-time",
        ),
        pytest.param(FakeOidcProvider(token_claims={"acr": 2}), id="acr-not-text"),
        pytest.param(
            FakeOidcProvider(token_claims={"amr": "pwd"}), id="amr-not-a-list"
        ),
        pytest.param(FakeOidcProvider(token_claims={"sub": DROP}), id="missing-sub"),
    ],
)
async def test_an_id_token_failing_a_check_is_refused_once(monkeypatch, provider):
    login = Login(monkeypatch, provider, existing_email="user@example.com")

    with pytest.raises(OidcResponseNotVerifiedError):
        await login.sign_in(email="new.person@example.com")

    assert _token_posts(provider) == 1
    assert login.users._created_user is None
    assert login.redis._store == {}


async def test_an_azp_naming_eneo_admits_several_audiences(monkeypatch):
    provider = FakeOidcProvider(
        token_claims={"aud": ["eneo-client", "another-client"], "azp": "eneo-client"}
    )
    login = Login(monkeypatch, provider, existing_email="user@example.com")

    assert login.signed_in_user(await login.sign_in())


@pytest.mark.parametrize("algorithm", ["ES256", "PS256", "EdDSA"])
async def test_a_provider_signing_with_another_allowed_algorithm_signs_in(
    monkeypatch, algorithm
):
    provider = FakeOidcProvider(algorithm=algorithm)
    login = Login(monkeypatch, provider, existing_email="user@example.com")

    assert login.signed_in_user(await login.sign_in())


@pytest.mark.parametrize("claim", ["at_hash", "auth_time"])
async def test_an_id_token_without_an_optional_claim_signs_in(monkeypatch, claim):
    provider = FakeOidcProvider(token_claims={claim: DROP})
    login = Login(monkeypatch, provider, existing_email="user@example.com")

    assert login.signed_in_user(await login.sign_in())
    (id_token,) = provider.id_tokens
    assert claim not in jwt.decode(id_token, options={"verify_signature": False})


class TestIssuerParameter:
    """RFC 9207: a provider that advertises it names itself in every response."""

    async def _callback(self, monkeypatch, provider, *, send_iss=True):
        login = Login(monkeypatch, provider, existing_email="user@example.com")
        started = await login.initiate()
        answer = provider.authorize(started.authorization_url)
        result = await federation_router.auth_callback(
            CallbackRequest(
                code=answer.code,
                state=started.state,
                iss=answer.iss if send_iss else None,
            ),
            login.container,
        )
        return login, result

    async def test_an_advertised_and_matching_parameter_is_accepted(self, monkeypatch):
        provider = FakeOidcProvider(advertise_iss_parameter=True)

        login, result = await self._callback(monkeypatch, provider)

        assert login.signed_in_user(result)

    async def test_a_missing_parameter_is_refused_when_advertised(self, monkeypatch):
        provider = FakeOidcProvider(advertise_iss_parameter=True)

        with pytest.raises(OidcResponseNotVerifiedError):
            await self._callback(monkeypatch, provider, send_iss=False)

        assert _token_posts(provider) == 0

    @pytest.mark.parametrize("advertised", [True, False])
    async def test_a_mismatching_parameter_is_refused(self, monkeypatch, advertised):
        provider = FakeOidcProvider(
            advertise_iss_parameter=advertised, iss_parameter="https://other.example"
        )

        with pytest.raises(OidcResponseNotVerifiedError):
            await self._callback(monkeypatch, provider)

        assert _token_posts(provider) == 0

    async def test_a_provider_without_the_parameter_signs_in(self, monkeypatch):
        login, result = await self._callback(monkeypatch, FakeOidcProvider())

        assert login.signed_in_user(result)


class TestIssuerBoundAtInitiate:
    """The transaction keeps the issuer and the RFC 9207 support the provider
    had when the sign-in started; a later change does not reach the callback."""

    async def _started(self, monkeypatch, provider, *, db_mode=True, **claims):
        login = Login(
            monkeypatch, provider, db_mode=db_mode, existing_email="user@example.com"
        )
        started = await login.initiate()
        answer = provider.authorize(started.authorization_url, **claims)
        return login, started, answer

    async def test_support_withdrawn_after_initiate_still_requires_iss(
        self, monkeypatch
    ):
        provider = FakeOidcProvider(advertise_iss_parameter=True)
        login, started, answer = await self._started(monkeypatch, provider)
        provider.advertise_iss_parameter = False
        oidc_profile._discovery_cache.clear()

        with pytest.raises(OidcResponseNotVerifiedError):
            await federation_router.auth_callback(
                CallbackRequest(code=answer.code, state=started.state),
                login.container,
            )

        assert _token_posts(provider) == 0
        assert login.users._created_user is None

    async def test_support_announced_after_initiate_does_not_require_iss(
        self, monkeypatch
    ):
        provider = FakeOidcProvider()
        login, started, answer = await self._started(monkeypatch, provider)
        provider.advertise_iss_parameter = True
        oidc_profile._discovery_cache.clear()

        result = await federation_router.auth_callback(
            CallbackRequest(code=answer.code, state=started.state), login.container
        )

        assert login.signed_in_user(result)

    @pytest.mark.parametrize(
        "db_mode", [True, False], ids=["stored-issuer", "discovery-issuer"]
    )
    @pytest.mark.parametrize("sent", ["initiate-issuer", "changed-issuer"])
    async def test_an_issuer_changed_after_initiate_ends_the_sign_in(
        self, monkeypatch, db_mode, sent
    ):
        """The code never reaches a configuration the sign-in did not start
        against, whichever issuer the response names."""
        provider = FakeOidcProvider(advertise_iss_parameter=True)
        # A first sign-in, so success would create the account.
        login, started, answer = await self._started(
            monkeypatch, provider, db_mode=db_mode, email="new.person@example.com"
        )
        changed = "https://changed.example.org"
        if db_mode:
            login.tenant.federation_config["issuer"] = changed
        else:
            provider.discovery_overrides["issuer"] = changed
            oidc_profile._discovery_cache.clear()
        callback = CallbackRequest(
            code=answer.code,
            state=started.state,
            iss=answer.iss if sent == "initiate-issuer" else changed,
        )

        with pytest.raises(OidcTransactionInvalidError):
            await federation_router.auth_callback(callback, login.container)

        assert _token_posts(provider) == 0
        assert login.users._created_user is None
        assert login.audit.logged_events == []


async def test_the_verified_authentication_carries_the_provider_facts(monkeypatch):
    provider = FakeOidcProvider(token_claims={"acr": "level-2", "amr": ["pwd", "otp"]})
    install(monkeypatch, provider)
    profile = await load_profile(
        provider.federation_config(), discovery_ttl_seconds=3600
    )
    transaction = OidcTransaction.start(
        "login",
        redirect_uri=REDIRECT_URI,
        tenant_id="tenant",
        tenant_slug="example",
        config_version=None,
        issuer=profile.issuer,
        iss_parameter_supported=profile.iss_parameter_supported,
    )
    answer = provider.authorize(
        build_authorization_request(profile, transaction, state="state")
    )

    verified = await verify_response(
        profile,
        transaction,
        CallbackResponse(code=answer.code),
        jwks_ttl_seconds=3600,
        correlation_id="facts",
    )

    assert (verified.issuer, verified.client_id, verified.subject) == (
        provider.issuer,
        provider.client_id,
        "subject-0001",
    )
    assert (verified.acr, verified.amr) == ("level-2", ("pwd", "otp"))
    assert verified.auth_time == provider.session_auth_time
    assert verified.identity().email == "user@example.com"


class FailingRedis(FakeRedis):
    async def setex(self, key: str, ttl: int, value: str) -> None:
        raise ConnectionError("redis unavailable")

    async def getdel(self, key: str) -> str | None:
        raise ConnectionError("redis unavailable")


class PendingRedis(FakeRedis):
    """A store whose named commands never answer, like a connection that
    stops responding without closing."""

    def __init__(self, *pending: str, store: dict[str, str] | None = None):
        super().__init__()
        self._pending = pending
        self._store = dict(store or {})
        self.commands: list[str] = []

    async def _answer(self, command: str) -> None:
        self.commands.append(command)
        if command in self._pending:
            await asyncio.Event().wait()

    async def setex(self, key: str, ttl: int, value: str) -> None:
        await self._answer("setex")
        await super().setex(key, ttl, value)

    async def get(self, key: str) -> str | None:
        await self._answer("get")
        return await super().get(key)

    async def getdel(self, key: str) -> str | None:
        await self._answer("getdel")
        return await super().getdel(key)


class TestStoreDeadline:
    """Every Redis call of a sign-in has a deadline; the shared pool sets no
    command timeout, so a silent connection would otherwise hold it forever."""

    @pytest.fixture(autouse=True)
    def short_deadline(self, monkeypatch):
        monkeypatch.setattr(oidc_transaction, "STORE_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(federation_router, "STORE_TIMEOUT_SECONDS", 0.05)

    async def test_a_silent_store_at_initiate_is_unavailable(self, monkeypatch):
        login = Login(monkeypatch, FakeOidcProvider())
        login.container._redis_client = PendingRedis("setex")

        with pytest.raises(OidcLoginUnavailableError):
            await asyncio.wait_for(login.initiate(), 2)

    async def test_a_silent_getdel_counts_as_used(self, monkeypatch):
        """Its outcome is unknown, so the transaction is never written back."""
        provider = FakeOidcProvider()
        login = Login(monkeypatch, provider, existing_email="user@example.com")
        started = await login.initiate()
        answer = provider.authorize(started.authorization_url)
        silent = PendingRedis("getdel", store=login.redis._store)
        login.container._redis_client = silent

        with pytest.raises(OidcLoginUnavailableError):
            await asyncio.wait_for(
                federation_router.auth_callback(
                    CallbackRequest(code=answer.code, state=started.state),
                    login.container,
                ),
                2,
            )

        assert "setex" not in silent.commands
        assert _token_posts(provider) == 0
        assert login.audit.logged_events == []

    async def test_a_silent_debug_read_does_not_hold_up_sign_in(self, monkeypatch):
        from eneo.observability import debug_toggle

        monkeypatch.setattr(
            debug_toggle, "_last_refresh", datetime.min.replace(tzinfo=timezone.utc)
        )
        login = Login(
            monkeypatch, FakeOidcProvider(), existing_email="user@example.com"
        )
        login.container._redis_client = PendingRedis("get")

        assert login.signed_in_user(await asyncio.wait_for(login.sign_in(), 2))

    @pytest.mark.parametrize("command", ["setex", "getdel"])
    async def test_cancelling_a_waiting_call_stays_a_cancellation(
        self, monkeypatch, command
    ):
        monkeypatch.setattr(oidc_transaction, "STORE_TIMEOUT_SECONDS", 30)
        store = PendingRedis(command)
        if command == "setex":
            call = save_transaction(
                store,
                OidcTransaction.start(
                    "login",
                    redirect_uri=REDIRECT_URI,
                    tenant_id="tenant",
                    tenant_slug="example",
                    config_version=None,
                    issuer="https://idp.example.org",
                    iss_parameter_supported=False,
                ),
                ttl_seconds=600,
            )
        else:
            call = take_transaction(store, "transaction")
        task = asyncio.ensure_future(call)
        await asyncio.sleep(0)

        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


class TestTransactionStore:
    async def test_sign_in_cannot_start_without_redis(self, monkeypatch):
        login = Login(monkeypatch, FakeOidcProvider())
        login.container._redis_client = None

        with pytest.raises(OidcLoginUnavailableError):
            await login.initiate()

    async def test_sign_in_cannot_start_when_redis_fails(self, monkeypatch):
        login = Login(monkeypatch, FakeOidcProvider())
        login.container._redis_client = FailingRedis()

        with pytest.raises(OidcLoginUnavailableError):
            await login.initiate()

    async def test_sign_in_cannot_start_when_redis_cannot_be_built(self, monkeypatch):
        login = Login(monkeypatch, FakeOidcProvider())

        def unavailable():
            raise RuntimeError("no redis configured")

        login.container.redis_client = unavailable

        with pytest.raises(OidcLoginUnavailableError):
            await login.initiate()

    @pytest.mark.parametrize("store", [None, FailingRedis()], ids=["absent", "failing"])
    async def test_a_callback_without_a_working_store_is_unavailable(
        self, monkeypatch, store
    ):
        provider = FakeOidcProvider()
        login = Login(monkeypatch, provider)
        started = await login.initiate()
        answer = provider.authorize(started.authorization_url)
        login.container._redis_client = store

        with pytest.raises(OidcLoginUnavailableError):
            await federation_router.auth_callback(
                CallbackRequest(code=answer.code, state=started.state),
                login.container,
            )

        assert _token_posts(provider) == 0
        assert login.users._created_user is None
        assert login.audit.logged_events == []

    async def test_an_unknown_transaction_is_invalid(self, monkeypatch):
        provider = FakeOidcProvider()
        login = Login(monkeypatch, provider)
        started = await login.initiate()
        answer = provider.authorize(started.authorization_url)
        login.redis._store.clear()

        with pytest.raises(OidcTransactionInvalidError):
            await federation_router.auth_callback(
                CallbackRequest(code=answer.code, state=started.state),
                login.container,
            )

        assert _token_posts(provider) == 0
        assert login.users._created_user is None

    async def test_a_transaction_without_the_expected_issuer_is_invalid(
        self, monkeypatch
    ):
        """One written before the transaction kept the issuer never falls
        back to the profile's."""
        provider = FakeOidcProvider()
        login = Login(monkeypatch, provider, existing_email="user@example.com")
        started = await login.initiate()
        answer = provider.authorize(started.authorization_url)
        (key,) = login.redis._store
        stored = json.loads(login.redis._store[key])
        login.redis._store[key] = json.dumps(
            {
                name: value
                for name, value in stored.items()
                if name not in ("issuer", "iss_parameter_supported")
            }
        )

        with pytest.raises(OidcTransactionInvalidError):
            await federation_router.auth_callback(
                CallbackRequest(code=answer.code, state=started.state),
                login.container,
            )

        assert _token_posts(provider) == 0

    async def test_a_transaction_admits_one_callback(self, monkeypatch):
        provider = FakeOidcProvider()
        login = Login(monkeypatch, provider)
        started = await login.initiate()
        answer = provider.authorize(started.authorization_url)
        callback = CallbackRequest(code=answer.code, state=started.state)
        await federation_router.auth_callback(callback, login.container)

        with pytest.raises(OidcTransactionInvalidError):
            await federation_router.auth_callback(callback, login.container)

        assert _token_posts(provider) == 1
        assert [
            event["metadata"]["provisioning_method"]
            for event in login.audit.logged_events
        ] == ["jit_federation"]


async def test_discovery_and_keys_are_fetched_once_for_several_logins(monkeypatch):
    provider = FakeOidcProvider()
    login = Login(monkeypatch, provider, existing_email="user@example.com")

    await login.sign_in()
    await login.sign_in()

    gets = [url for method, url in provider.requests if method == "GET"]
    assert gets.count(provider.discovery_url) == 1
    assert gets.count(provider.jwks_uri) == 1


def _gets(provider: FakeOidcProvider, url: str) -> int:
    return [u for method, u in provider.requests if method == "GET"].count(url)


class TestDiscovery:
    async def _profile(self, provider):
        return await load_profile(
            provider.federation_config(), discovery_ttl_seconds=3600
        )

    async def test_concurrent_misses_fetch_discovery_once(self, monkeypatch):
        provider = FakeOidcProvider()
        install(monkeypatch, provider)

        await asyncio.gather(*(self._profile(provider) for _ in range(5)))

        assert _gets(provider, provider.discovery_url) == 1

    async def test_a_failed_fetch_is_not_retried_at_once(self, monkeypatch):
        provider = FakeOidcProvider(down=True)
        install(monkeypatch, provider)

        for _ in range(2):
            with pytest.raises(OidcProviderError):
                await self._profile(provider)

        assert _gets(provider, provider.discovery_url) == 1

    async def test_discovery_recovers_after_the_cooldown(self, monkeypatch):
        provider = FakeOidcProvider(down=True)
        install(monkeypatch, provider)
        monkeypatch.setattr(oidc_profile, "DISCOVERY_RETRY_SECONDS", 0)
        with pytest.raises(OidcProviderError):
            await self._profile(provider)
        provider.down = False

        assert (await self._profile(provider)).issuer == provider.issuer
        assert _gets(provider, provider.discovery_url) == 2


class TestSigningKeys:
    @pytest.mark.parametrize("use", ["sig", None], ids=["sig", "omitted"])
    async def test_a_signing_key_verifies_the_id_token(self, monkeypatch, use):
        login = Login(
            monkeypatch,
            FakeOidcProvider(key_use=use),
            existing_email="user@example.com",
        )

        assert login.signed_in_user(await login.sign_in())

    async def test_an_encryption_key_never_verifies_a_signature(self, monkeypatch):
        login = Login(
            monkeypatch,
            FakeOidcProvider(key_use="enc"),
            existing_email="user@example.com",
        )

        with pytest.raises(OidcResponseNotVerifiedError):
            await login.sign_in()

    async def test_issuers_sharing_a_jwks_address_share_its_keys(self, monkeypatch):
        provider = FakeOidcProvider()
        install(monkeypatch, provider)

        for issuer in ("https://a.example", "https://b.example", "https://a.example"):
            await get_federation_signing_key(
                issuer=issuer,
                jwks_uri=provider.jwks_uri,
                kid=provider.kid,
                ttl_seconds=3600,
            )

        assert _gets(provider, provider.jwks_uri) == 1

    async def test_a_failed_key_fetch_cools_down_for_every_issuer(self, monkeypatch):
        provider = FakeOidcProvider(down=True)
        install(monkeypatch, provider)

        def key_for(issuer: str):
            return get_federation_signing_key(
                issuer=issuer,
                jwks_uri=provider.jwks_uri,
                kid=provider.kid,
                ttl_seconds=3600,
            )

        with pytest.raises(JWKSFetchError):
            await key_for("https://a.example")
        with pytest.raises(AuthenticationException):
            await key_for("https://b.example")

        assert _gets(provider, provider.jwks_uri) == 1


@pytest.mark.parametrize("db_mode", [True, False], ids=["db-mode", "env-mode"])
async def test_the_provider_identity_reaches_account_admission(monkeypatch, db_mode):
    seen: list[FederatedIdentity] = []
    admit = UserService.resolve_federated_user

    async def spy(self, *, identity, **kwargs):
        seen.append(identity)
        return await admit(self, identity=identity, **kwargs)

    monkeypatch.setattr(UserService, "resolve_federated_user", spy)
    provider = FakeOidcProvider()
    login = Login(
        monkeypatch, provider, db_mode=db_mode, existing_email="user@example.com"
    )

    await login.sign_in()

    (identity,) = seen
    assert (identity.issuer, identity.client_id, identity.subject) == (
        provider.issuer,
        provider.client_id,
        "subject-0001",
    )


class TestProfileDefaults:
    def _profile(self, discovery: dict[str, Any] | None = None, **config: Any):
        provider = FakeOidcProvider()
        return build_profile(
            {**provider.federation_config(), **config},
            {**provider.discovery(), **(discovery or {})},
        )

    def test_absent_keys_keep_todays_behaviour(self):
        profile = self._profile()

        assert profile.signing_algorithms == ("RS256",)
        assert profile.email_claim == "email"
        assert profile.email_verified_claims == ("email_verified", "xms_edov")
        assert profile.scopes == ("openid", "email", "profile")

    def test_without_advertised_algorithms_rs256_is_used(self):
        profile = self._profile({"id_token_signing_alg_values_supported": None})

        assert profile.signing_algorithms == ("RS256",)

    def test_advertised_algorithms_are_limited_to_the_allowlist(self):
        profile = self._profile(
            {"id_token_signing_alg_values_supported": ["none", "HS256", "ES256"]}
        )

        assert profile.signing_algorithms == ("ES256",)

    def test_configured_algorithms_win_within_the_allowlist(self):
        profile = self._profile(signing_algorithms=["PS256", "HS512"])

        assert profile.signing_algorithms == ("PS256",)

    @pytest.mark.parametrize(
        "config",
        [
            {"signing_algorithms": ["HS256"]},
            {"signing_algorithms": []},
            {"email_verified_claims": []},
            {"email_verified_claims": ["email_verified", 1]},
            {"scopes": "openid"},
        ],
    )
    def test_unusable_configured_keys_are_refused(self, config):
        with pytest.raises(OidcProviderError):
            self._profile(**config)

    def test_the_stored_issuer_wins_over_discovery(self):
        profile = self._profile({"issuer": "https://elsewhere.example"})

        assert profile.issuer == FakeOidcProvider().issuer

    def test_discovery_names_the_issuer_when_none_is_stored(self):
        profile = self._profile(issuer=None)

        assert profile.issuer == FakeOidcProvider().issuer


class TestEmailVerifiedClaims:
    CLAIMS = {"sub": "subject", "email": "user@example.com"}

    def _identity(self, claims: dict[str, Any], *names: str) -> FederatedIdentity:
        extra = {"email_verified_claims": names} if names else {}
        return FederatedIdentity.from_claims(
            {**self.CLAIMS, **claims},
            issuer="https://idp.example.org",
            client_id="eneo-client",
            **extra,
        )

    def test_the_first_claim_sent_decides(self):
        assert (
            self._identity({"email_verified": "0", "xms_edov": True}).email_verified
            is False
        )
        assert self._identity({"xms_edov": True}).email_verified is True

    def test_a_configured_list_replaces_the_default(self):
        assert (
            self._identity({"xms_edov": True}, "email_verified").email_verified is False
        )
        assert (
            self._identity(
                {"domain_verified": True}, "email_verified", "domain_verified"
            ).email_verified
            is True
        )

    def test_an_explicit_false_never_falls_through(self):
        with pytest.raises(ValueError, match="not verified"):
            self._identity(
                {"email_verified": False, "domain_verified": True},
                "email_verified",
                "domain_verified",
            )
        with pytest.raises(ValueError, match="not verified"):
            self._identity({"email_verified": False}, "xms_edov", "email_verified")

    def test_a_standard_flag_left_out_of_the_list_does_not_decide(self):
        assert (
            self._identity(
                {"email_verified": False, "domain_verified": True}, "domain_verified"
            ).email_verified
            is True
        )

    def test_the_configured_order_decides_before_the_standard_flag(self):
        assert (
            self._identity(
                {"email_verified": False, "xms_edov": True},
                "xms_edov",
                "email_verified",
            ).email_verified
            is True
        )

    def test_the_subject_is_required(self):
        with pytest.raises(ValueError, match="subject"):
            FederatedIdentity.from_claims(
                {"email": "user@example.com", "email_verified": True},
                issuer="https://idp.example.org",
                client_id="eneo-client",
            )


class TestHttpAnswers:
    """The typed refusals reach clients with their status and string code."""

    async def _client(self, login):
        from httpx import ASGITransport, AsyncClient

        from eneo.main.config import get_settings, set_settings
        from eneo.server.endpoint_routes import endpoint_routes
        from eneo.server.main import get_application

        original = get_settings()
        set_settings(
            original.model_copy(
                update={
                    "browser_session_enabled": True,
                    "web_app_enabled": False,
                    "environment": "production",
                    "jwt_secret": login.settings.jwt_secret,
                }
            )
        )
        app = get_application()
        for route in endpoint_routes(app.routes):
            if route.dependant:
                for dependency in route.dependant.dependencies:
                    if dependency.name == "container":
                        app.dependency_overrides[dependency.call] = (
                            lambda: login.container
                        )
        client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://eneo.example.org",
            follow_redirects=False,
        )
        return client, lambda: set_settings(original)

    async def test_initiate_without_redis_answers_503(self, monkeypatch):
        login = Login(monkeypatch, FakeOidcProvider())
        login.container._redis_client = None
        client, restore = await self._client(login)
        try:
            async with client:
                answer = await client.get(
                    "/api/v1/auth/initiate", params={"tenant": login.tenant.slug}
                )
        finally:
            restore()

        assert answer.status_code == 503
        assert answer.json()["code"] == "oidc_login_unavailable"
        assert answer.json()["eneo_error_code"] == 9077

    async def test_a_reused_callback_answers_400(self, monkeypatch):
        provider = FakeOidcProvider()
        login = Login(monkeypatch, provider, existing_email="user@example.com")
        started = await login.initiate()
        answer = provider.authorize(started.authorization_url)
        login.redis._store.clear()
        client, restore = await self._client(login)
        try:
            async with client:
                refused = await client.post(
                    "/api/v1/auth/callback",
                    json={"code": answer.code, "state": started.state},
                )
        finally:
            restore()

        assert refused.status_code == 400
        assert refused.json()["code"] == "oidc_transaction_invalid"
        assert refused.json()["eneo_error_code"] == 9078

    async def test_an_unverified_response_answers_401(self, monkeypatch):
        provider = FakeOidcProvider(token_claims={"nonce": "another-nonce"})
        login = Login(monkeypatch, provider, existing_email="user@example.com")
        started = await login.initiate()
        answer = provider.authorize(started.authorization_url)
        client, restore = await self._client(login)
        try:
            async with client:
                refused = await client.post(
                    "/api/v1/auth/callback",
                    json={"code": answer.code, "state": started.state},
                )
        finally:
            restore()

        assert refused.status_code == 401
        assert refused.json()["code"] == "oidc_response_not_verified"
        assert refused.json()["eneo_error_code"] == 9079

    @pytest.mark.parametrize(
        ("break_store", "detail_code"),
        [
            ("callback", "oidc_login_unavailable"),
            ("miss", "oidc_transaction_invalid"),
            ("issuer-changed", "oidc_transaction_invalid"),
        ],
    )
    async def test_the_browser_login_names_the_refusal(
        self, monkeypatch, break_store, detail_code
    ):
        from eneo.authentication.browser_session_service import (
            BrowserSessionService,
        )

        provider = FakeOidcProvider()
        login = Login(monkeypatch, provider, existing_email="user@example.com")
        sessions = AsyncMock(spec=BrowserSessionService)
        login.container.browser_session_service = lambda: sessions
        client, restore = await self._client(login)
        try:
            async with client:
                started = await client.get(
                    "/api/v1/auth/browser/initiate",
                    params={"tenant": login.tenant.slug},
                    headers={"Sec-Fetch-Site": "same-origin"},
                )
                assert started.status_code == 303
                answer = provider.authorize(started.headers["location"])
                state = _query(started.headers["location"])["state"][0]
                if break_store == "callback":
                    login.container._redis_client = FailingRedis()
                elif break_store == "miss":
                    login.redis._store.clear()
                else:
                    login.tenant.federation_config["issuer"] = "https://changed.example"
                finished = await client.get(
                    "/login/callback",
                    params={"code": answer.code, "state": state},
                    headers={"Sec-Fetch-Site": "cross-site"},
                )
        finally:
            restore()

        assert finished.status_code == 303
        location = _query(finished.headers["location"])
        assert location["detailCode"] == [detail_code]
        assert login.users._created_user is None
        sessions.start.assert_not_called()
        assert _token_posts(provider) == 0

    async def test_the_browser_login_cannot_start_without_redis(self, monkeypatch):
        login = Login(monkeypatch, FakeOidcProvider())
        login.container._redis_client = None
        client, restore = await self._client(login)
        try:
            async with client:
                started = await client.get(
                    "/api/v1/auth/browser/initiate",
                    params={"tenant": login.tenant.slug},
                    headers={"Sec-Fetch-Site": "same-origin"},
                )
        finally:
            restore()

        assert started.status_code == 303
        assert _query(started.headers["location"])["detailCode"] == [
            "oidc_login_unavailable"
        ]
