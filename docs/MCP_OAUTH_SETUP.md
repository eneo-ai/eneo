# MCP OAuth Setup — Same-IdP Token Broker

**Audience:** Developers wiring up per-user authentication for MCP servers; ops engineers deploying the same flow in production.
**Goal:** Walk through how Eneo's MCP token broker exchanges a user's IdP session for an audience-bound bearer token an MCP server can validate, end-to-end. Concept first, then the recipe.

---

## 1. What this enables

When an MCP server is registered with `auth_scope=per_user`, every tool call carries an audience-bound JWT minted *for that specific user* by the same IdP they logged in to. The user authenticates once at login; from that point on Eneo's broker performs the token exchange behind the scenes, with no second consent screen, no shared service account, and no static credentials living in the database.

This is the same trust model as [Microsoft On-Behalf-Of](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow) and [Keycloak's Standard Token Exchange](https://www.keycloak.org/securing-apps/token-exchange), generalised to "any RFC 8693 conformant IdP".

---

## 2. Specs you'll want at hand

The broker speaks several specs cooperatively. The first time you debug a failure, having these tabs open shortens the loop dramatically:

| RFC | What it gives us |
|-----|------------------|
| [RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) | OAuth 2.0 Authorization Framework — the authorization-code login that gets the user in |
| [RFC 6750](https://datatracker.ietf.org/doc/html/rfc6750) | Bearer Token Usage — `Authorization: Bearer <jwt>` on every MCP call |
| [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) | OAuth 2.0 Token Exchange — the broker's grant type; how a subject access token becomes an audience-bound token |
| [RFC 8707](https://datatracker.ietf.org/doc/html/rfc8707) | Resource Indicators — the `resource` parameter sent alongside `audience`; Keycloak ignores one and Entra ignores the other, so the broker sends both |
| [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) | OAuth 2.0 Protected Resource Metadata — the `.well-known/oauth-protected-resource` document the MCP server uses to advertise its expected IdP |
| [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html), [OIDC Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html) | The identity layer on top of OAuth 2.0 |

---

## 3. Components

| Component | Role | Implementation |
|-----------|------|----------------|
| **IdP** (Keycloak in this guide) | Authenticates the user, mints id/access/refresh tokens, performs RFC 8693 exchange | Keycloak 26.2+ with `--features=token-exchange-standard-v2` |
| **Eneo backend** | Persists encrypted IdP tokens; runs the broker that mints audience-bound tokens at call time | `backend/src/intric/mcp_servers/application/mcp_token_broker.py` |
| **MCP server** (e.g. Ladan) | Advertises its expected IdP via RFC 9728; validates incoming JWT bearer tokens | Any HTTP server that implements RFC 9728 + standard JWT validation |

---

## 4. End-to-end flow

There are two phases — a one-time login (RFC 6749) followed by per-tool-call exchange (RFC 8693). Each step is implemented in code referenced after the diagram.

```
┌─ Login phase (one-time per user session) ───────────────────────────────┐
│  Browser ──(1)──► eneo /auth/federation/initiate                        │
│  eneo    ──(2)──► IdP /auth?response_type=code                          │
│                       &scope=openid+email+profile+offline_access        │
│  Browser ──(3)──► IdP login UI                                          │
│  IdP     ──(4)──► Browser  /login/callback?code=...                     │
│  Browser ──(5)──► eneo /auth/federation/callback?code=...               │
│  eneo    ──(6)──► IdP /token (grant_type=authorization_code)            │
│  eneo    ◄─(7)──  { access_token, refresh_token, id_token }             │
│  eneo    persists Fernet-encrypted tokens in idp_user_tokens            │
│  eneo    issues its own session JWT in the `auth` cookie                │
└─────────────────────────────────────────────────────────────────────────┘

┌─ MCP tool call (every chat turn touching a per_user MCP server) ────────┐
│  Browser ──(8)──► eneo /chat/...                                        │
│  eneo    builds token_provider_map for the conversation's MCP servers   │
│  At first tool dispatch, the MCP proxy connects to the MCP server:      │
│  eneo    ──(9)──► MCP server /.well-known/oauth-protected-resource      │
│  eneo    ◄─(10)── { resource: <id>, authorization_servers: [<iss>] }    │
│  eneo    enforces same-IdP gate: <iss> must match the user's IdP issuer │
│  eneo    loads access_token from idp_user_tokens                        │
│           refreshes via refresh_token if access_token expired           │
│  eneo    ──(11)── IdP /token (RFC 8693 grant)                           │
│           grant_type=urn:ietf:params:oauth:grant-type:token-exchange    │
│           subject_token=<user access_token>                             │
│           subject_token_type=...:token-type:access_token                │
│           audience=<resource>                                           │
│           resource=<resource>            (RFC 8707, sent for parity)    │
│           client_id=<eneo client>                                       │
│           client_secret=<eneo secret>                                   │
│  eneo    ◄─(12)── { access_token: <audience-bound JWT>, expires_in }    │
│  eneo    caches Fernet-encrypted token in mcp_exchanged_tokens          │
│  eneo    ──(13)── MCP server POST <endpoint> Authorization: Bearer JWT  │
│  MCP svr validates: signature (JWKS), iss, aud, exp                     │
│  MCP svr ◄─(14)── tool response                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

Things worth highlighting:

- **The user authenticates once.** Steps (11)–(12) are a backchannel server-to-server call; the user is not involved. This is what `offline_access` buys you (see §6 — Token storage).
- **Step (10)'s `authorization_servers` is the trust anchor.** If it does not include the issuer Eneo authenticated the user against, the broker raises `MCPSameIdpMismatchError` and refuses to exchange. The check lives in `_enforce_same_idp_gate` in the broker module.
- **The `audience` value in step (11) is matched by the IdP against a registered `client_id`.** In Keycloak that means: the audience name must equal the `client_id` of a client registered in the same realm — even if that client doesn't itself authenticate to Keycloak. It's there purely as an audience target.
- **Caching.** Step (12)'s token is stored in `mcp_exchanged_tokens` keyed on `(mcp_server_id, subject_type, subject_id)`. Subsequent tool calls within the cached token's lifetime skip steps (9)–(12) entirely. Cache safety margin is 60 seconds before `expires_at` (see `CACHE_SAFETY_MARGIN_SECONDS` in the broker).

---

## 5. Requirements checklist

When something fails, walk this list top-to-bottom. Each line is something the broker assumes is true.

- [ ] The MCP server publishes a valid RFC 9728 document at `<base>/.well-known/oauth-protected-resource`
- [ ] The document's `authorization_servers` includes the canonical issuer string the IdP emits in tokens (with Keycloak this is whatever `KC_HOSTNAME` resolves to; see §7)
- [ ] Eneo's `tenant.federation_config` carries `issuer`, `idp_kind` (`keycloak` or `entra`), `token_endpoint`, `client_id`, and `client_secret` (Fernet-encrypted)
- [ ] The IdP client that performs the exchange (the `eneo` client) has client authentication on AND the equivalent of Keycloak's "Standard token exchange" capability on
- [ ] For Keycloak: server started with `--features=token-exchange-standard-v2` (only required in 26.2; later versions may move the gate)
- [ ] The `audience` value the broker sends corresponds to a registered `client_id` in the IdP. For Keycloak that's a client in the same realm. The audience is set via `mcp_servers.target_resource_or_scope` (per-server override) or, falling back, via PRM's `resource` field
- [ ] The user has a non-revoked row in `idp_user_tokens` (i.e., logged in via the IdP since the last issuer change or revocation)
- [ ] The MCP server's JWT validator accepts the audience string the broker uses (the simplest convention is: pick one name, e.g. `ladan`, and use it as both the Keycloak client_id and the MCP server's expected audience)

---

## 6. Token storage

Two tables, both encrypted with Fernet (AES-128-CBC + HMAC) using `ENCRYPTION_KEY` from the backend env. Ciphertext envelope is `enc:fernet:v1:<base64>`. All encryption/decryption goes through `EncryptionService` in `backend/src/intric/settings/encryption_service.py`.

### `idp_user_tokens`

One row per `(user_id, idp_issuer)`. Defined in `backend/src/intric/database/tables/idp_user_tokens_table.py`. Surface in `backend/src/intric/authentication/oidc_token_store.py`:

| Column | Notes |
|--------|-------|
| `refresh_token_ciphertext` | The long-lived refresh token. Required for the broker to mint anything. |
| `access_token_ciphertext` | The short-lived access token. Used directly if not expired; otherwise the broker refreshes it. |
| `access_token_expires_at` | Used with `CACHE_SAFETY_MARGIN_SECONDS` to decide whether to refresh. |
| `scopes_granted` | Set of scopes the IdP returned. |
| `revoked_at` | Set on logout or when a refresh attempt returns `invalid_grant`. The broker treats revoked rows as missing. |

- **Written** by `OidcTokenStore.upsert()` from the federation callback after every successful login.
- **Rotated** by `OidcTokenStore.refresh_idp_token()` when the cached access token nears expiry; if the IdP returns a new refresh token, it is rotated in place.
- **Revoked** on logout by `OidcTokenStore.revoke()`, which zeroes both ciphertext fields and stamps `revoked_at`.

### `mcp_exchanged_tokens`

One row per `(mcp_server_id, subject_type, subject_id)`. Defined in `backend/src/intric/database/tables/mcp_exchanged_tokens_table.py`. Caches the audience-bound token so that, within its lifetime, repeated tool calls skip the IdP round-trip:

| Column | Notes |
|--------|-------|
| `token_ciphertext` | The minted audience-bound JWT. |
| `expires_at` | Cache validity. Reads use `expires_at > now() + CACHE_SAFETY_MARGIN_SECONDS`. |
| `audience` | What the broker sent as the audience parameter (kept for debugging). |
| `idp_issuer` | What the broker verified as the issuer (kept for debugging). |

- **Purged for one server** via `MCPTokenBroker.purge_cache_for_server()` whenever the server's `auth_scope`, `expected_idp_issuer`, or `http_url` changes (the cached audience is no longer guaranteed valid).
- **Purged for one user** via `MCPTokenBroker.purge_cache_for_user()` on logout.

### Eneo's own session

The `auth` cookie issued at the end of step (7) is **independent** of the IdP refresh token. It's signed by `JWT_SECRET`, has its own lifetime (24h by default), and never touches `idp_user_tokens`. The broker is the only path in Eneo that consumes the persisted IdP tokens. This is what makes "offline_access only matters for the broker" true in practice (see below).

### `offline_access`

Refresh tokens issued without the `offline_access` scope expire on idle (Keycloak default: 30 minutes). That's painful for a backend broker that may go unused for hours and then need to mint a fresh token. Eneo requests `offline_access` at login so that the persisted refresh token is offline-capable — it only expires when the user explicitly logs out or an admin revokes the session.

This is configured via `tenant.federation_config.scopes` (must include `"offline_access"`). The federation callback hands the resulting refresh token to `OidcTokenStore.upsert()` exactly like a normal refresh token; the broker doesn't distinguish.

### Key rotation

Rotating `ENCRYPTION_KEY` makes both tables unreadable. Two options:

- **Drop-and-rebuild**: `DELETE FROM idp_user_tokens; DELETE FROM mcp_exchanged_tokens;`. Users will be forced through a fresh login; the cache rebuilds organically.
- **Rolling rotation**: re-encrypt every row's ciphertext under both keys during a maintenance window. Not implemented in Eneo today — open a follow-up if you need it.

---

## 7. The dual-hostname problem

Whenever the IdP is reachable under different hostnames from different network positions (e.g., a published port for the browser vs. a container-network port for the backend), tokens issued with one hostname won't validate against discovery documents fetched from the other. Symptoms: `iss` mismatches, JWKS-fetch failures, `Authentication failed (401 Unauthorized)`.

Keycloak's answer is the `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` setting. With it, the **issuer** advertised in discovery + tokens is always `KC_HOSTNAME` (canonical), while **backchannel URLs** (`token_endpoint`, `userinfo_endpoint`, `jwks_uri`) in the discovery document follow the caller's `Host` header. Net effect: the browser and the backend can hit different URLs but every token has the same `iss`.

In dev that means: the browser uses `http://keycloak.orb.local:8090` (published port), the eneo and Ladan containers use `http://keycloak.orb.local:8080` (container-internal port), and both see `iss=http://keycloak.orb.local:8090/realms/<realm>` in tokens.

In prod the same setting matters when your TLS-terminating ingress sits in front of an in-cluster service — backend pods may resolve a different URL than what browsers see externally.

---

## 8. Local setup (OrbStack devcontainer-based)

Concrete, copy-paste recipe. Tested against Keycloak 26.2 + OrbStack on macOS.

### 8.1 Run Keycloak

```bash
docker run -d --name keycloak \
  -p 8090:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  -e KC_HOSTNAME=http://keycloak.orb.local:8090 \
  -e KC_HOSTNAME_STRICT=false \
  -e KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true \
  -e KC_HTTP_ENABLED=true \
  -v keycloak-data:/opt/keycloak/data \
  quay.io/keycloak/keycloak:26.2 \
  start-dev --features=token-exchange-standard-v2
```

### 8.2 Make the hostname resolve

Add to `/etc/hosts` on the Mac (browser-side):

```
127.0.0.1 keycloak.orb.local
```

Then attach Keycloak to every Docker network that needs to reach it — give it the `keycloak.orb.local` alias on each so backend containers resolve the same hostname:

```bash
docker network connect --alias keycloak.orb.local eneo keycloak
docker network connect --alias keycloak.orb.local ladan_default keycloak
```

Verify all three paths return HTTP 200:

```bash
# Mac browser path
curl -s -m 3 -o /dev/null -w 'mac    → %{http_code}\n' http://keycloak.orb.local:8090/realms/local/.well-known/openid-configuration
# Eneo container path
docker exec eneo_devcontainer-eneo-1 bash -c "curl -s -m 3 -o /dev/null -w 'eneo   → %{http_code}\n' http://keycloak.orb.local:8080/realms/local/.well-known/openid-configuration"
# Ladan container path
docker exec ladan-dev bash -c "curl -s -m 3 -o /dev/null -w 'ladan  → %{http_code}\n' http://keycloak.orb.local:8080/realms/local/.well-known/openid-configuration"
```

### 8.3 Keycloak realm + clients

Via the admin UI at `http://keycloak.orb.local:8090/admin/` (admin/admin from step 8.1):

1. **Realm**: create `local`.
2. **Client `eneo`** (the broker requester):
   - General settings: Client ID `eneo`, type OpenID Connect.
   - Capability config: **Client authentication** On. **Standard token exchange** On. Standard flow + Direct access grants On.
   - Login settings: Valid redirect URIs = `http://localhost:3000/login/callback`. Web origins = `+`.
   - Credentials: copy the client secret; you'll paste it into `.env` next.
3. **Client `ladan`** (the audience target; one client per MCP server resource):
   - General settings: Client ID `ladan`, type OpenID Connect.
   - Capability config: Client authentication Off. Standard token exchange is greyed out — that's fine. Standard flow on.
   - It needs no credentials and no redirect URIs; it exists purely so Keycloak's audience lookup finds a registered name.
4. **A user**: create a user in the `local` realm; set a password under Credentials. The user's email must match an Eneo user (Eneo matches OIDC users by email).

### 8.4 Eneo backend `.env`

```
OIDC_DISCOVERY_ENDPOINT=http://keycloak.orb.local:8080/realms/local/.well-known/openid-configuration
OIDC_CLIENT_ID=eneo
OIDC_CLIENT_SECRET=<client secret from step 8.3>
OIDC_TENANT_ID=<UUID of the tenant the user belongs to>
PUBLIC_ORIGIN=http://localhost:3000
ENCRYPTION_KEY=<base64 Fernet key — see backend/.env.template>
```

Frontend `.env` mirrors the OIDC trio plus its own `PUBLIC_ORIGIN`. See `frontend/apps/web/.env.example`.

### 8.5 Populate `tenant.federation_config`

> **The broker requires DB-resident federation config.** The `OIDC_*` environment variables are the **legacy** single-tenant path — they get a user logged in, but they do not populate the fields the token broker needs (`issuer`, `idp_kind`, `token_endpoint`, encrypted `client_secret`). Any deployment that uses per-user MCP authentication MUST configure the tenant's `federation_config` row, regardless of `FEDERATION_PER_TENANT_ENABLED`.
>
> In production the recommended path is the sysadmin federation API ([Multi-Tenant OIDC Setup Guide](./MULTITENANT_OIDC_SETUP_GUIDE.md)). For local dev, the script below populates the row directly. See §13 for the architectural cleanup that would let env-based deployments derive these fields automatically.

Run this script once after configuring the env:

```bash
docker exec -u vscode eneo_devcontainer-eneo-1 bash -i -c "cd /workspace/backend && uv run python -c '
import asyncio, json
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from intric.main.config import get_settings
from intric.settings.encryption_service import EncryptionService
s = get_settings()
async def m():
    enc = EncryptionService(s.encryption_key)
    issuer = \"http://keycloak.orb.local:8090/realms/local\"
    backchannel = \"http://keycloak.orb.local:8080/realms/local\"
    fc = {
        \"provider\": \"keycloak\",
        \"idp_kind\": \"keycloak\",
        \"issuer\": issuer,
        \"token_endpoint\": f\"{backchannel}/protocol/openid-connect/token\",
        \"discovery_endpoint\": f\"{backchannel}/.well-known/openid-configuration\",
        \"client_id\": s.oidc_client_id,
        \"client_secret\": enc.encrypt(s.oidc_client_secret),
        \"scopes\": [\"openid\", \"email\", \"profile\", \"offline_access\"],
    }
    e = create_async_engine(f\"postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}\")
    async with e.begin() as c:
        await c.execute(text(\"UPDATE tenants SET federation_config = :fc WHERE id = :id\"),
                        {\"fc\": json.dumps(fc), \"id\": s.oidc_tenant_id})
asyncio.run(m())
'"
```

The split issuer (`:8090`) vs `token_endpoint`/`discovery_endpoint` (`:8080`) is the dual-hostname workaround from §7.

### 8.6 Register the MCP server in Eneo

Via the admin UI:

1. **Admin → MCP servers → Add**
2. Name: `Grounding` (or your MCP server name)
3. HTTP URL: the MCP server's URL (e.g., `http://host.docker.internal:3001/mcp/grounding`)
4. Authentication: **SSO (zero-trust via samma IdP)** → **Per användare**
5. Advanced (required for Entra ID — also used here): **Audience / scope (target URI)** = `ladan` (the Keycloak client_id from step 8.3)
6. Save.

### 8.7 Log in (re-login if you were already signed in)

After the federation_config row exists and `offline_access` is in the scopes:

1. Log out of Eneo
2. Log in via Keycloak — accept the one-time **Offline Access** consent prompt
3. The federation callback writes a fresh `idp_user_tokens` row with an offline-capable refresh token

### 8.8 MCP server side (Ladan or any other resource server)

The MCP server must:

1. **Expose RFC 9728 metadata** at `<base>/.well-known/oauth-protected-resource`:
   ```json
   {
     "resource": "ladan",
     "authorization_servers": ["http://keycloak.orb.local:8090/realms/local"]
   }
   ```
   The `resource` value is used by the broker as the default audience (overridable per-server via the `target_resource_or_scope` field in §8.6).

2. **Validate the JWT** with these settings:
   - `issuer` = `http://keycloak.orb.local:8090/realms/local` (the canonical KC_HOSTNAME-shaped issuer)
   - `audience` = `ladan` (the Keycloak client_id, matching `target_resource_or_scope`)
   - `jwksUri` = `http://keycloak.orb.local:8080/realms/local/protocol/openid-connect/certs` — **backchannel port**, since the MCP server's container can't reach the published port; the discovery doc fetched at port 8080 returns this jwks_uri via `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`

   Example with `jose`:
   ```ts
   import { createRemoteJWKSet, jwtVerify } from 'jose'

   const JWKS = createRemoteJWKSet(
     new URL('http://keycloak.orb.local:8080/realms/local/protocol/openid-connect/certs')
   )

   const { payload } = await jwtVerify(token, JWKS, {
     issuer: 'http://keycloak.orb.local:8090/realms/local',
     audience: 'ladan',
   })
   ```

   Example with `jsonwebtoken` + `jwks-rsa`:
   ```ts
   import jwt from 'jsonwebtoken'
   import jwksRsa from 'jwks-rsa'

   const client = jwksRsa({
     jwksUri: 'http://keycloak.orb.local:8080/realms/local/protocol/openid-connect/certs',
   })
   const getKey: jwt.GetPublicKeyOrSecret = (header, cb) => {
     client.getSigningKey(header.kid!, (err, key) => cb(err, key?.getPublicKey()))
   }
   jwt.verify(token, getKey, {
     issuer: 'http://keycloak.orb.local:8090/realms/local',
     audience: 'ladan',
     algorithms: ['RS256'],
   })
   ```

---

## 9. Production delta

Most of §8 carries over to production. The differences:

- **DNS, not /etc/hosts.** Pick one canonical IdP hostname (e.g., `https://sso.yourcompany.example/`), expose it via your ingress, and use it as `KC_HOSTNAME`. Browsers, backend pods, and MCP server pods must all resolve and reach the same name. No port games, no `/etc/hosts` entries.
- **HTTPS everywhere.** Set `KC_HOSTNAME=https://...`. JWKS fetches automatically follow the discovery doc's `jwks_uri`, which inherits the scheme; Eneo's broker uses `aiohttp` defaults and trusts the system root CAs.
- **Backchannel-dynamic still worth keeping.** Even in-cluster, an in-cluster service URL can differ from the externally-visible URL. Leaving `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` on means pods that talk to Keycloak via the cluster-internal service still get a working `token_endpoint`, while tokens carry the canonical external `iss`.
- **`tenant.federation_config` is required in production.** Configure each tenant's IdP via the sysadmin federation API ([Multi-Tenant OIDC Setup Guide](./MULTITENANT_OIDC_SETUP_GUIDE.md)). The env-var-only single-tenant path is legacy and doesn't carry the broker fields — even single-tenant production deployments running per-user MCP must write `federation_config`.
- **Session lifetime.** Keep `offline_access` in scopes; tune realm-level "SSO Session Idle" and "SSO Session Max" to your operational tolerance.
- **Audit pipeline.** The broker emits `mcp_token_exchanged` and `mcp_token_exchange_denied` events via `audit_service.log_async`. Confirm your central audit pipeline ingests them; they're how you'd answer "who exchanged a token for what audience and when".
- **Token-exchange policy hardening.** By default the `eneo` client can request audience-bound tokens for *any* registered client in the realm. To restrict it to specific resources, configure per-target policies on each MCP-server client (Keycloak admin → client → Permissions). Belt-and-suspenders; not a current vulnerability.

---

## 10. Verification

End-to-end smoke test once the setup is in place.

```bash
# 1. Confirm idp_user_tokens has a non-revoked row after fresh login
docker exec -u vscode eneo_devcontainer-eneo-1 bash -i -c \
  "cd /workspace/backend && uv run python -c 'import asyncio; from sqlalchemy.ext.asyncio import create_async_engine; from sqlalchemy import text; from intric.main.config import get_settings;
s = get_settings()
async def m():
    e = create_async_engine(f\"postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}\")
    async with e.connect() as c:
        r = await c.execute(text(\"SELECT idp_issuer, revoked_at, length(refresh_token_ciphertext) > 0 FROM idp_user_tokens\"))
        for row in r: print(row)
asyncio.run(m())'"
```

Expect one row with `revoked_at=None` and `refresh_token_ciphertext` populated.

```bash
# 2. After triggering an MCP tool call from chat, decode the cached exchange token
docker exec -u vscode eneo_devcontainer-eneo-1 bash -i -c \
  "cd /workspace/backend && uv run python -c 'import asyncio, base64, json; from sqlalchemy.ext.asyncio import create_async_engine; from sqlalchemy import text; from intric.main.config import get_settings; from intric.settings.encryption_service import EncryptionService;
s = get_settings(); enc = EncryptionService(s.encryption_key)
async def m():
    e = create_async_engine(f\"postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}\")
    async with e.connect() as c:
        r = await c.execute(text(\"SELECT token_ciphertext FROM mcp_exchanged_tokens ORDER BY issued_at DESC LIMIT 1\"))
        token = enc.decrypt(r.scalar_one())
        p = token.split(\".\")[1]; p += \"=\" * ((4 - len(p) % 4) % 4)
        print(json.dumps(json.loads(base64.urlsafe_b64decode(p)), indent=2))
asyncio.run(m())'"
```

Expect a JWT payload with `iss=<canonical issuer>`, `aud=<your audience>`, and `azp=eneo`.

```bash
# 3. Confirm backend logs show no broker failures
docker logs eneo_devcontainer-eneo-1 --tail 200 2>&1 | grep -iE "MCPProxy|broker|token.exchange" | tail -20
```

Expect `[MCPProxy] Connected to '<server>' in <N>ms`, no `Failed to pre-connect`, no `IdP rejected token exchange`.

```bash
# 4. Confirm the MCP server logs show successful validation
# Whatever your MCP server's log surface is - look for the request landing without 401
```

---

## 11. Common failure modes

A condensed list, mapped to the broker's error vocabulary.

| Symptom in logs | Likely cause |
|-----------------|--------------|
| `MCPBrokerConfigurationError: PRM discovery failed` | The MCP server doesn't serve `/.well-known/oauth-protected-resource`, or it returns non-JSON / HTML |
| `MCPSameIdpMismatchError` | PRM `authorization_servers` doesn't include the issuer the broker resolved (mismatched hostnames, see §7) |
| `MCPNotAuthenticatedError` | `idp_user_tokens` row missing or revoked. User must log in via the IdP again. Common after rotating `KC_HOSTNAME` |
| `IdP rejected refresh token with invalid_grant` | Refresh token expired (idle-expiry; add `offline_access` to scopes), or issuer changed since the row was written |
| `IdP rejected token exchange: HTTP 401 unauthorized_client / invalid_client_credentials` | Client authentication failed at the IdP. Most often: `client_secret` wasn't decrypted before sending (broker bug fixed in `mcp_token_broker.py`), or Standard Token Exchange is not enabled on the client |
| `IdP rejected token exchange: HTTP 400 invalid_client Audience not found` | The `audience` value isn't a registered client_id in the IdP. Register a client matching the audience name, or set `target_resource_or_scope` on the MCP server to a name that *is* registered |
| `Authentication failed (401 Unauthorized). Check your bearer token.` | The MCP server itself rejected the minted token. Decode the token (§10 step 2) and compare against the MCP server's `audience` / `issuer` / `jwksUri` configuration |

---

## 12. Where this lives in code

| Concern | File |
|---------|------|
| Broker entrypoint, RFC 8693 / OBO dispatch | `backend/src/intric/mcp_servers/application/mcp_token_broker.py` |
| Strategy: Keycloak (RFC 8693) | `backend/src/intric/mcp_servers/application/token_exchange/rfc8693.py` |
| Strategy: Entra ID (OBO) | `backend/src/intric/mcp_servers/application/token_exchange/entra.py` |
| Token storage (encryption + refresh) | `backend/src/intric/authentication/oidc_token_store.py` |
| Token cache table | `backend/src/intric/database/tables/mcp_exchanged_tokens_table.py` |
| User-token table | `backend/src/intric/database/tables/idp_user_tokens_table.py` |
| Encryption primitives | `backend/src/intric/settings/encryption_service.py` |
| Federation callback (persists IdP tokens) | `backend/src/intric/authentication/federation_router.py` |
| MCP-server admin UI | `frontend/apps/web/src/routes/(app)/admin/mcp-servers/` |
| User-facing connection status | `frontend/apps/web/src/routes/(app)/account/mcp-connections/` |

---

## 13. Known gaps / follow-ups

**Legacy single-tenant env config does not feed the broker.** `OIDC_DISCOVERY_ENDPOINT` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` are the legacy way of configuring user-facing OIDC. They get a user logged in, but the broker reads from `tenant.federation_config`, and `federation_startup_migration.py` only copies env-OIDC into that row when `FEDERATION_PER_TENANT_ENABLED=true`. Result: a single-tenant deployment that wants per-user MCP today must either flip to federation mode + use the sysadmin API, or populate the row out-of-band (the §8.5 script).

Two cleaner futures, pick one if/when this gets prioritised:

- Lift the `federation_enabled` gate in `federation_startup_migration.py` so env-OIDC is mirrored into `federation_config` regardless of mode.
- Or have `CredentialResolver.get_federation_config()` derive `issuer` / `idp_kind` / `token_endpoint` from `OIDC_DISCOVERY_ENDPOINT` in its single-tenant branch, and have the broker call the resolver instead of reading the JSONB column directly.

The second is the cleaner architectural move — single source of truth for "which IdP does this tenant use", consulted by both login and broker.

---

## See also

- [Multi-Tenant OIDC Setup Guide](./MULTITENANT_OIDC_SETUP_GUIDE.md) — provisioning user-facing OIDC per tenant
- [Federation Per Tenant](./FEDERATION_PER_TENANT.md) — the federation feature overview
- [Architecture](./ARCHITECTURE.md) — system context
