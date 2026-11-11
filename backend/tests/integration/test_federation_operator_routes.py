"""Golden behaviour of the operator (super API key) federation routes.

Written against the router before the tenant-admin door moved its logic into
TenantFederationService; the operator routes must answer exactly as before.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from eneo.database.database import sessionmanager
from eneo.main.config import get_settings, set_settings
from eneo.tenants.tenant_repo import TenantRepository
from tests.integration.test_federation_tenant_admin import _audit_rows, _store

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SECRET = "super-secret"
TEMPLATED_ISSUER_GUIDANCE = (
    "The provider's issuer is a template; use your own directory's discovery endpoint"
)


def _idp(slug: str) -> dict[str, str]:
    base = f"https://idp.{slug}.local"
    return {
        "discovery_endpoint": f"{base}/.well-known/openid-configuration",
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "jwks_uri": f"{base}/jwks",
    }


def _discovery(idp: dict[str, str]) -> dict[str, dict[str, str]]:
    return {
        idp["discovery_endpoint"]: {
            key: idp[key]
            for key in (
                "issuer",
                "authorization_endpoint",
                "token_endpoint",
                "jwks_uri",
            )
        }
    }


async def _tenant(client: AsyncClient, key: str, slug: str) -> dict:
    response = await client.post(
        "/api/v1/sysadmin/tenants/",
        json={"name": slug, "display_name": slug, "state": "active"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _stored(tenant_id: str) -> dict:
    async with sessionmanager.session() as session, session.begin():
        tenant = await TenantRepository(session).get(UUID(tenant_id))
        assert tenant is not None
        return dict(tenant.federation_config)


def _put_body(slug: str, idp: dict[str, str]) -> dict:
    return {
        "provider": "entra",
        "client_id": f"client-{slug}",
        "client_secret": SECRET,
        "discovery_endpoint": idp["discovery_endpoint"],
        "canonical_public_origin": f"https://{slug}.eneo.test",
        "redirect_path": "/auth/callback",
        "allowed_domains": [f"{slug}.gov"],
    }


async def test_put_get_patch_test_delete_answer_as_before(
    client: AsyncClient,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    slug = f"fed-golden-{uuid4().hex[:6]}"
    tenant = await _tenant(client, super_admin_token, slug)
    idp = _idp(slug)
    oidc_mock(discovery=_discovery(idp))
    headers = {"X-API-Key": super_admin_token}
    url = f"/api/v1/sysadmin/tenants/{tenant['id']}/federation"

    put = await client.put(url, json=_put_body(slug, idp), headers=headers)
    assert put.status_code == 200, put.text
    assert put.json() == {
        "tenant_id": tenant["id"],
        "provider": "entra",
        "masked_secret": "...cret",
        "message": "Federation config for entra replaced successfully",
    }
    stored = await _stored(tenant["id"])
    assert stored["client_secret"].startswith("enc:fernet:v")
    assert SECRET not in str(stored)
    assert {
        k: v for k, v in stored.items() if k not in ("client_secret", "encrypted_at")
    } == {
        "provider": "entra",
        "discovery_endpoint": idp["discovery_endpoint"],
        "client_id": f"client-{slug}",
        "scopes": ["openid", "email", "profile"],
        "allowed_domains": [f"{slug}.gov"],
        "claims_mapping": {
            "email": "email",
            "subject": "sub",
            "username": "sub",
            "name": "name",
        },
        "issuer": idp["issuer"],
        "authorization_endpoint": idp["authorization_endpoint"],
        "token_endpoint": idp["token_endpoint"],
        "userinfo_endpoint": None,
        "jwks_uri": idp["jwks_uri"],
        "token_endpoint_auth_method": "client_secret_post",
        "token_endpoint_auth_methods_supported": [],
        "canonical_public_origin": f"https://{slug}.eneo.test",
        "redirect_path": "/auth/callback",
    }

    get = await client.get(url, headers=headers)
    assert get.status_code == 200, get.text
    body = get.json()
    assert datetime.fromisoformat(body.pop("configured_at")) == datetime.fromisoformat(
        stored["encrypted_at"]
    )
    assert body == {
        "provider": "entra",
        "client_id": f"client-{slug}",
        "masked_secret": "...cret",
        "issuer": idp["issuer"],
        "allowed_domains": [f"{slug}.gov"],
        "allowed_endpoint_hosts": [],
        "additional_redirect_uris": [],
        "signing_algorithms": None,
        "email_verified_claims": None,
        "subject_claim": "sub",
        "encryption_status": "encrypted",
    }

    patch = await client.patch(
        url, json={"client_id": "renamed", "allowed_domains": []}, headers=headers
    )
    assert patch.status_code == 200, patch.text
    assert patch.json() == {
        "tenant_id": tenant["id"],
        "provider": "entra",
        "masked_secret": "...cret",
        "message": "Federation config for entra updated successfully",
    }
    patched = await _stored(tenant["id"])
    assert patched == {**stored, "client_id": "renamed", "allowed_domains": []}

    probe = await client.post(f"{url}/test", headers=headers)
    assert probe.status_code == 200, probe.text
    assert probe.json() == {
        "success": True,
        "message": "Federation config is valid and IdP is reachable",
        "issuer": idp["issuer"],
    }

    delete = await client.delete(url, headers=headers)
    assert delete.status_code == 200, delete.text
    assert delete.json() == {
        "tenant_id": tenant["id"],
        "message": "Federation config deleted successfully",
    }
    assert await _stored(tenant["id"]) == {}


async def test_optional_provider_keys_round_trip(
    client: AsyncClient,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    slug = f"fed-keys-{uuid4().hex[:6]}"
    tenant = await _tenant(client, super_admin_token, slug)
    idp = _idp(slug)
    oidc_mock(discovery=_discovery(idp))
    headers = {"X-API-Key": super_admin_token}
    url = f"/api/v1/sysadmin/tenants/{tenant['id']}/federation"
    keys = {
        "signing_algorithms": ["ES256", "RS256"],
        "email_verified_claims": ["email_verified"],
    }

    put = await client.put(url, json={**_put_body(slug, idp), **keys}, headers=headers)
    assert put.status_code == 200, put.text
    stored = await _stored(tenant["id"])
    assert {key: stored[key] for key in keys} == keys
    get = await client.get(url, headers=headers)
    assert {key: get.json()[key] for key in keys} == keys

    patch = await client.patch(
        url,
        json={"signing_algorithms": ["PS256"], "email_verified_claims": None},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    patched = await _stored(tenant["id"])
    assert patched["signing_algorithms"] == ["PS256"]
    assert "email_verified_claims" not in patched
    get = await client.get(url, headers=headers)
    assert get.json()["signing_algorithms"] == ["PS256"]
    assert get.json()["email_verified_claims"] is None


async def test_the_subject_claim_is_set_by_put_and_patch(
    client: AsyncClient,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    slug = f"fed-subject-{uuid4().hex[:6]}"
    tenant = await _tenant(client, super_admin_token, slug)
    idp = _idp(slug)
    oidc_mock(discovery=_discovery(idp))
    headers = {"X-API-Key": super_admin_token}
    url = f"/api/v1/sysadmin/tenants/{tenant['id']}/federation"

    put = await client.put(
        url, json={**_put_body(slug, idp), "subject_claim": "oid"}, headers=headers
    )
    assert put.status_code == 200, put.text
    assert (await _stored(tenant["id"]))["claims_mapping"] == {
        "email": "email",
        "subject": "oid",
        "username": "sub",
        "name": "name",
    }
    assert (await client.get(url, headers=headers)).json()["subject_claim"] == "oid"

    patch = await client.patch(
        url, json={"subject_claim": "employee_id"}, headers=headers
    )
    assert patch.status_code == 200, patch.text
    stored = await _stored(tenant["id"])
    assert stored["claims_mapping"] == {
        "email": "email",
        "subject": "employee_id",
        "username": "sub",
        "name": "name",
    }

    for refused in ({"subject_claim": "email"}, {"subject_claim": None}):
        response = await client.patch(url, json=refused, headers=headers)
        assert response.status_code == 422, (refused, response.text)
        assert await _stored(tenant["id"]) == stored
    unchanged = await client.patch(url, json={"client_id": "next"}, headers=headers)
    assert unchanged.status_code == 200, unchanged.text
    assert (await _stored(tenant["id"]))["claims_mapping"] == stored["claims_mapping"]


async def test_operator_errors_answer_as_before(
    client: AsyncClient,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    slug = f"fed-golden-err-{uuid4().hex[:6]}"
    tenant = await _tenant(client, super_admin_token, slug)
    idp = _idp(slug)
    oidc_mock(discovery={idp["discovery_endpoint"]: ({"error": "down"}, 500)})
    headers = {"X-API-Key": super_admin_token}
    url = f"/api/v1/sysadmin/tenants/{tenant['id']}/federation"

    unauthenticated = await client.get(url)
    assert unauthenticated.status_code == 401

    missing_get = await client.get(url, headers=headers)
    assert missing_get.status_code == 404
    assert missing_get.json()["detail"] == "No federation config found for tenant"

    missing_patch = await client.patch(url, json={"client_id": "x"}, headers=headers)
    assert missing_patch.status_code == 404
    assert missing_patch.json()["detail"] == "No federation config found for tenant"

    bad_discovery = await client.put(url, json=_put_body(slug, idp), headers=headers)
    assert bad_discovery.status_code == 502
    assert (
        bad_discovery.json()["detail"] == "Failed to fetch discovery document: HTTP 500"
    )
    assert await _stored(tenant["id"]) == {}

    oidc_mock(discovery=_discovery(idp))
    assert (
        await client.put(url, json=_put_body(slug, idp), headers=headers)
    ).status_code == 200
    empty_patch = await client.patch(url, json={}, headers=headers)
    assert empty_patch.status_code == 400
    assert (
        empty_patch.json()["detail"] == "At least one field must be provided for patch"
    )

    original = get_settings()
    set_settings(original.model_copy(update={"federation_enabled": False}))
    try:
        disabled = await client.get(url, headers=headers)
    finally:
        set_settings(original)
    assert disabled.status_code == 404
    assert disabled.json()["detail"] == "Federation is not enabled"


async def test_a_templated_issuer_is_refused_before_it_is_saved(
    client: AsyncClient,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    """A multi-tenant discovery document (Entra ``common``) names an issuer
    template no ID token can match: the save is refused, not the sign-in."""
    slug = f"fed-golden-tpl-{uuid4().hex[:6]}"
    tenant = await _tenant(client, super_admin_token, slug)
    idp = _idp(slug)
    template = "https://login.microsoftonline.com/{tenantid}/v2.0"
    headers = {"X-API-Key": super_admin_token}
    url = f"/api/v1/sysadmin/tenants/{tenant['id']}/federation"

    oidc_mock(discovery=_discovery({**idp, "issuer": template}))
    refused_put = await client.put(url, json=_put_body(slug, idp), headers=headers)
    assert refused_put.status_code == 400
    assert refused_put.json()["detail"] == TEMPLATED_ISSUER_GUIDANCE
    assert await _stored(tenant["id"]) == {}

    oidc_mock(discovery=_discovery(idp))
    saved = await client.put(url, json=_put_body(slug, idp), headers=headers)
    assert saved.status_code == 200, saved.text
    stored = await _stored(tenant["id"])
    common = _idp(f"{slug}-common")
    oidc_mock(discovery=_discovery({**common, "issuer": template}))
    refused_patch = await client.patch(
        url, json={"discovery_endpoint": common["discovery_endpoint"]}, headers=headers
    )
    assert refused_patch.status_code == 400
    assert refused_patch.json()["detail"] == TEMPLATED_ISSUER_GUIDANCE
    assert await _stored(tenant["id"]) == stored
    assert len(await _audit_rows(tenant["id"])) == 1  # only the accepted PUT

    # A stored issuer wins over discovery at sign-in; a config moved from the
    # OIDC_* settings stores none and signs in with discovery's.
    await _store(
        tenant["id"],
        {key: value for key, value in stored.items() if key not in DISCOVERY_KEYS},
    )
    oidc_mock(discovery=_discovery({**idp, "issuer": template}))
    probe = await client.post(f"{url}/test", headers=headers)
    assert probe.status_code == 400
    assert probe.json()["detail"] == TEMPLATED_ISSUER_GUIDANCE


NO_ALLOWED_ALGORITHM = "The provider signs with no algorithm Eneo accepts"
# What discovery decides, as a save stores it.
DISCOVERY_KEYS = (
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "userinfo_endpoint",
    "jwks_uri",
    "token_endpoint_auth_method",
    "token_endpoint_auth_methods_supported",
)


async def _registered(
    client: AsyncClient, key: str, oidc_mock, prefix: str
) -> tuple[dict, dict[str, str], str, dict[str, str]]:
    slug = f"{prefix}-{uuid4().hex[:6]}"
    tenant = await _tenant(client, key, slug)
    idp = _idp(slug)
    headers = {"X-API-Key": key}
    url = f"/api/v1/sysadmin/tenants/{tenant['id']}/federation"
    oidc_mock(discovery=_discovery(idp))
    saved = await client.put(url, json=_put_body(slug, idp), headers=headers)
    assert saved.status_code == 200, saved.text
    return tenant, idp, url, headers


def _signing_only_with(idp: dict[str, str], *algorithms: str) -> dict:
    discovery = _discovery(idp)
    discovery[idp["discovery_endpoint"]] = {
        **discovery[idp["discovery_endpoint"]],
        "id_token_signing_alg_values_supported": list(algorithms),
    }
    return discovery


async def test_the_operator_test_refuses_a_provider_that_signs_with_no_allowed_algorithm(
    client: AsyncClient, super_admin_token: str, oidc_mock, mock_transcription_models
):
    _, idp, url, headers = await _registered(
        client, super_admin_token, oidc_mock, "fed-test-alg"
    )
    oidc_mock(discovery=_signing_only_with(idp, "HS256"))

    probe = await client.post(f"{url}/test", headers=headers)

    assert probe.status_code == 400
    assert probe.json()["detail"] == NO_ALLOWED_ALGORITHM


async def test_the_operator_test_answers_502_when_discovery_is_unreachable(
    client: AsyncClient, super_admin_token: str, oidc_mock, mock_transcription_models
):
    _, idp, url, headers = await _registered(
        client, super_admin_token, oidc_mock, "fed-test-down"
    )
    oidc_mock(discovery={idp["discovery_endpoint"]: ({}, 503)})

    probe = await client.post(f"{url}/test", headers=headers)

    assert probe.status_code == 502
    assert probe.json()["detail"] == "Failed to fetch discovery document: HTTP 503"


async def test_a_put_refuses_a_provider_that_signs_with_no_allowed_algorithm(
    client: AsyncClient, super_admin_token: str, oidc_mock, mock_transcription_models
):
    slug = f"fed-put-alg-{uuid4().hex[:6]}"
    tenant = await _tenant(client, super_admin_token, slug)
    idp = _idp(slug)
    oidc_mock(discovery=_signing_only_with(idp, "HS256"))

    refused = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant['id']}/federation",
        json=_put_body(slug, idp),
        headers={"X-API-Key": super_admin_token},
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == NO_ALLOWED_ALGORITHM
    assert await _stored(tenant["id"]) == {}


async def test_a_patch_to_a_new_discovery_stores_its_issuer_endpoints_and_a_usable_auth_method(
    client: AsyncClient, super_admin_token: str, oidc_mock, mock_transcription_models
):
    tenant, idp, url, headers = await _registered(
        client, super_admin_token, oidc_mock, "fed-patch-move"
    )
    moved = _idp(f"moved-{uuid4().hex[:6]}")
    discovery = _discovery(moved)
    discovery[moved["discovery_endpoint"]] = {
        **discovery[moved["discovery_endpoint"]],
        "token_endpoint_auth_methods_supported": ["private_key_jwt"],
    }
    oidc_mock(discovery={**_discovery(idp), **discovery})

    patch = await client.patch(
        url, json={"discovery_endpoint": moved["discovery_endpoint"]}, headers=headers
    )

    assert patch.status_code == 200, patch.text
    stored = await _stored(tenant["id"])
    assert {key: stored.get(key) for key in DISCOVERY_KEYS} == {
        "issuer": moved["issuer"],
        "authorization_endpoint": moved["authorization_endpoint"],
        "token_endpoint": moved["token_endpoint"],
        "userinfo_endpoint": None,
        "jwks_uri": moved["jwks_uri"],
        # The method sign-in uses when the provider lists neither post nor basic.
        "token_endpoint_auth_method": "client_secret_post",
        "token_endpoint_auth_methods_supported": ["private_key_jwt"],
    }


async def test_a_patch_to_a_moved_config_fetches_nothing(
    client: AsyncClient, super_admin_token: str, oidc_mock, mock_transcription_models
):
    # A config moved from the OIDC_* settings stores no issuer or endpoints:
    # sign-in reads them from discovery. Editing it needs no provider.
    tenant, idp, url, headers = await _registered(
        client, super_admin_token, oidc_mock, "fed-patch-moved"
    )
    moved = {
        key: value
        for key, value in (await _stored(tenant["id"])).items()
        if key not in DISCOVERY_KEYS
    }
    await _store(tenant["id"], moved)
    oidc_mock(discovery={idp["discovery_endpoint"]: ({}, 503)})

    patch = await client.patch(url, json={"client_id": "renamed"}, headers=headers)

    assert patch.status_code == 200, patch.text
    assert await _stored(tenant["id"]) == {**moved, "client_id": "renamed"}


async def test_a_patch_over_a_config_sign_in_cannot_use_is_refused_unchanged(
    client: AsyncClient, super_admin_token: str, oidc_mock, mock_transcription_models
):
    # Stored by hand: the subject claim is the email claim, which sign-in
    # refuses. A save over it stores nothing until the config is usable.
    tenant, _, url, headers = await _registered(
        client, super_admin_token, oidc_mock, "fed-patch-unusable"
    )
    unusable = {
        **await _stored(tenant["id"]),
        "claims_mapping": {"email": "upn", "subject": "upn"},
    }
    await _store(tenant["id"], unusable)

    refused = await client.patch(url, json={"client_id": "renamed"}, headers=headers)

    assert refused.status_code == 400
    assert refused.json()["detail"] == (
        "The claims mapping names the email claim as the subject claim"
    )
    assert await _stored(tenant["id"]) == unusable


@pytest.mark.parametrize("methods", [["client_secret_basic"], ["client_secret_post"]])
async def test_a_put_stores_the_auth_method_the_provider_lists(
    client: AsyncClient,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
    methods,
):
    slug = f"fed-put-method-{uuid4().hex[:6]}"
    tenant = await _tenant(client, super_admin_token, slug)
    idp = _idp(slug)
    discovery = _discovery(idp)
    discovery[idp["discovery_endpoint"]] = {
        **discovery[idp["discovery_endpoint"]],
        "token_endpoint_auth_methods_supported": methods,
    }
    oidc_mock(discovery=discovery)

    saved = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant['id']}/federation",
        json=_put_body(slug, idp),
        headers={"X-API-Key": super_admin_token},
    )

    assert saved.status_code == 200, saved.text
    stored = await _stored(tenant["id"])
    assert stored["token_endpoint_auth_method"] == methods[0]
    assert stored["token_endpoint_auth_methods_supported"] == methods


async def test_endpoints_on_another_host_need_the_host_listed(
    client: AsyncClient,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    """A discovery document cannot send the token request elsewhere: saving
    names the host to list, and emptying the list again is refused."""
    slug = f"fed-hosts-{uuid4().hex[:6]}"
    tenant = await _tenant(client, super_admin_token, slug)
    idp = {**_idp(slug), "token_endpoint": "https://tokens.example.net/token"}
    oidc_mock(discovery=_discovery(idp))
    headers = {"X-API-Key": super_admin_token}
    url = f"/api/v1/sysadmin/tenants/{tenant['id']}/federation"

    refused = await client.put(url, json=_put_body(slug, idp), headers=headers)
    assert refused.status_code == 400, refused.text
    assert "tokens.example.net" in refused.json()["detail"]
    assert await _stored(tenant["id"]) == {}

    listed = await client.put(
        url,
        json={**_put_body(slug, idp), "allowed_endpoint_hosts": ["Tokens.Example.net"]},
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    got = await client.get(url, headers=headers)
    assert got.json()["allowed_endpoint_hosts"] == ["tokens.example.net"]

    emptied = await client.patch(
        url, json={"allowed_endpoint_hosts": []}, headers=headers
    )
    assert emptied.status_code == 400, emptied.text
    assert "tokens.example.net" in emptied.json()["detail"]
    assert (await _stored(tenant["id"]))["allowed_endpoint_hosts"] == [
        "tokens.example.net"
    ]


async def test_a_discovery_endpoint_over_plain_http_is_refused(
    client: AsyncClient,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    slug = f"fed-http-{uuid4().hex[:6]}"
    tenant = await _tenant(client, super_admin_token, slug)
    idp = _idp(slug)
    oidc_mock(discovery={})
    body = {
        **_put_body(slug, idp),
        "discovery_endpoint": f"http://idp.{slug}.local/.well-known/openid-configuration",
    }

    refused = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant['id']}/federation",
        json=body,
        headers={"X-API-Key": super_admin_token},
    )

    assert refused.status_code == 422, refused.text
