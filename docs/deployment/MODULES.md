# Eneo Modules — Operator Guide

Modules are optional web applications that run next to an Eneo installation. Each module is a separate BFF container on its own domain and calls Eneo only through published backend APIs. Enabling or removing a module does not modify the core Eneo images.

> **Compatibility gate:** a compose file and a healthy container do not prove that login works. Deploy only a module release that explicitly declares support for Eneo's module-auth handoff and passes the end-to-end login smoke test in this guide. The deployment shape is aligned with the [Eneo modules example](https://github.com/CCimen/eneo-modules-example), but the module image remains responsible for implementing the callback, ticket exchange, state validation and module session.

> **Current delivery boundary:** the broker can issue and exchange login tickets, and `GET /api/v1/module-auth/{module_key}/session/` proves the dual-credential dependency against live state. The Tal till text Flow resource routes are not available on this branch, however. The diagnostic route is not an authorization preflight: every eventual Flow operation must enforce the dependency itself. The overlay and provisioning commands remain preparation, not authorization to production-enable the module.

## Ownership and security boundaries

Eneo core owns:

- the stable `module_key` registry and tenant assignment;
- the user's normal login and IdP integration;
- redirect URI and service-key binding;
- one-time ticket issuance and exchange;
- user and tenant authorization.

The module BFF owns:

- its browser session and CSRF protection;
- the pending one-time `state` value;
- the callback handler and immediate ticket exchange;
- storage of its scoped Eneo service key;
- calls to the published Flow/API contract.

The security model has four layers:

1. **Scoped credentials.** Each module gets one dedicated `sk_` service key with the narrowest scope and permission that works. The secret stays in the module's server environment and is never returned to the browser.
2. **Network isolation.** Modules join only `module_net`. That network is internal and has no route to PostgreSQL, Redis or the public internet. Backend and Traefik bridge the required boundaries.
3. **BFF isolation.** The browser talks only to the module domain. Server-side module code performs Eneo API calls and ticket exchange.
4. **Dual request authorization.** Every protected module operation must send both the bound service key and the module-user Bearer token. `require_module_request(<server-owned-module-key>)` validates the live service-key state, exact tenant-module binding, token audience, user, tenant and current assignment in one dependency. The resource route—not the diagnostic session call and not the BFF alone—must apply it on every request. Disabling the user, tenant, service key or module assignment takes effect on the next request — including on every token refresh, which runs the same dependency. A normal Eneo browser logout does not centrally revoke an already issued stateless module token; its residual lifetime is bounded by the short token TTL and, across refreshes, by the absolute session ceiling (`MODULE_AUTH_MAX_SESSION_HOURS`, default 8 hours from the original handoff).

Modules on the same `module_net` are not network-isolated from each other. Backend authorization and separately scoped service keys are therefore the real module-to-module authorization boundary.

## User login through Eneo

Modules do not register their own IdP clients. Eneo remains the installation's OIDC client:

1. The module generates a one-time `state`, binds it to the browser and navigates to Eneo's `/module-login` route.
2. Eneo uses the existing session or completes the normal IdP flow, verifies tenant/module access and redirects to the registered module callback with a short-lived ticket and the unchanged `state`.
3. The module verifies and consumes `state`, exchanges the ticket server-side with its registered service key, establishes its own session and removes ticket data from the browser URL.

The ticket is single-use, expires after about 30 seconds and is consumed with Redis `GETDEL`. The installation must use Redis 6.2 or newer; the bundled stack uses Redis 7.

### Module session lifetime and token refresh

The exchanged module user token is short-lived (`MODULE_AUTH_TOKEN_EXPIRY_MINUTES`, default 60). The exchange response carries `session_expires_at`: an absolute ceiling fixed at the original handoff (`MODULE_AUTH_MAX_SESSION_HOURS`, default 8 hours). A module renews its token with `POST /api/v1/module-auth/{module_key}/token/refresh/`, authenticated exactly like a resource call — bound service key plus the current, still-valid Bearer token. Refresh re-validates live user, tenant, key and assignment state, returns a token carrying the original handoff time, and clips the new expiry at the ceiling; it never accepts an expired token.

A module implementing refresh must:

- refresh proactively from server-side code — below roughly half the remaining token lifetime, and always before starting a long operation such as an upload;
- treat any refresh failure (`401` or `403`) as a signal to end its own session and restart the login handoff, which stays transparent while the user's Eneo session is alive;
- treat a small `expires_in` in a refresh response as the approaching ceiling, and complete or persist pending work before it;
- update its own session expiry from each response instead of assuming a fixed lifetime; the module session cookie must never outlive the token it wraps.

### Stable module identity

`module_key` is a case-sensitive public machine identity. For Tal till text the established value is `speech-to-text`.

- It is not the module row's database UUID.
- Treat it as immutable: a new key creates a new module identity.
- Use lowercase kebab-case for new keys. Registration enforces a URL-safe
  slug (letters and digits plus `.`, `_` or `-`, starting with a letter or
  digit) because the key travels as a URL path segment in the session and
  refresh routes, as the `MODULE_KEY` environment variable and as a
  JWT-audience suffix. A pre-existing row whose key does not meet this
  restriction keeps working as a feature-flag module but cannot be enabled
  for login handoff — register a new module key instead.
- The module image receives this value through the canonical `MODULE_KEY` environment variable.

### Required callback behavior

A module implementing this handoff must:

- Generate an unpredictable `state` value between 1 and 512 characters. Store it in a short-lived, one-time cookie with `HttpOnly`, `Secure` and `SameSite=Lax`; `SameSite=Strict` can drop the cookie on the cross-site top-level callback.
- Navigate the top-level browser to `${ENEO_PUBLIC_URL}/module-login` with exactly one non-empty `module_key`, `redirect_uri` and `state` parameter:

  ```text
  https://eneo.example.org/module-login
    ?module_key=speech-to-text
    &redirect_uri=https%3A%2F%2Ftal-till-text.example.org%2Fapi%2Fauth%2Fcallback
    &state=<opaque-random-state>
  ```

- Reject a missing, mismatched, expired or reused `state` before exchanging the ticket.
- Exchange the ticket from server-side code immediately, then redirect to a clean URL so neither `ticket` nor `state` remains in browser history.
- Serve the callback with `Referrer-Policy: no-referrer`, load no third-party resources and exclude query strings for `/module-login`, Eneo `/login` during handoff resume, and the module callback from access logs.

## Enable Tal till text

The commands below assume Bash, `curl` and `python3`. Run them from `docs/deployment`. Replace every quoted `CHANGE_ME` value before use.

### 1. Configure DNS

Point the module domain at the same ingress as Eneo:

```text
tal-till-text.example.org  A  203.0.113.10
```

Traefik provisions TLS after the module service starts and DNS resolves correctly.

### 2. Register and enable the module

Provisioning uses the installation's super-duper key. Runtime module traffic never receives this credential. `API_KEY_HEADER_NAME` must match the backend setting; the default is `X-API-Key`.

```bash
ENEO_URL="https://eneo.example.org"
API_KEY_HEADER_NAME="X-API-Key"
TENANT_ID="CHANGE_ME_TENANT_UUID"
MODULE_KEY="speech-to-text"
printf 'Super-duper key: '
IFS= read -r -s SUPER_DUPER_KEY
printf '\n'

# Reuse the existing immutable identity when the key is already registered.
MODULE_DB_ID=$(
  curl --fail-with-body -sS "$ENEO_URL/api/v1/modules/" \
    -H "$API_KEY_HEADER_NAME: $SUPER_DUPER_KEY" |
  python3 -c 'import json,sys; key=sys.argv[1]; print(next((m["id"] for m in json.load(sys.stdin)["items"] if m["name"] == key), ""))' "$MODULE_KEY"
)

if [ -z "$MODULE_DB_ID" ]; then
  MODULE_REQUEST=$(python3 -c 'import json,sys; print(json.dumps({"name": sys.argv[1]}))' "$MODULE_KEY")
  MODULE_RESPONSE=$(curl --fail-with-body -sS -X POST "$ENEO_URL/api/v1/modules/" \
    -H "$API_KEY_HEADER_NAME: $SUPER_DUPER_KEY" \
    -H "Content-Type: application/json" \
    -d "$MODULE_REQUEST")
  MODULE_DB_ID=$(printf '%s' "$MODULE_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
fi

# Targeted PUT is idempotent and preserves every other enabled module.
curl --fail-with-body -sS -X PUT \
  "$ENEO_URL/api/v1/modules/$TENANT_ID/$MODULE_DB_ID/" \
  -H "$API_KEY_HEADER_NAME: $SUPER_DUPER_KEY"
```

The older `POST /api/v1/modules/{tenant_id}/` endpoint replaces the tenant's complete module set. Do not use it to enable or disable one module.

### 3. Mint a dedicated service key

Log in as a tenant admin whose role may manage API keys. Reading credentials interactively avoids corrupting passwords containing `&`, `+` or `=` and keeps them out of shell history.

```bash
printf 'Admin email: '
IFS= read -r ADMIN_EMAIL
printf 'Admin password: '
IFS= read -r -s ADMIN_PASSWORD
printf '\n'

TOKEN_RESPONSE=$(curl --fail-with-body -sS -X POST \
  "$ENEO_URL/api/v1/users/login/token/" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=$ADMIN_EMAIL" \
  --data-urlencode "password=$ADMIN_PASSWORD")
unset ADMIN_PASSWORD
TOKEN=$(printf '%s' "$TOKEN_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

SPACE_ID="CHANGE_ME_DEDICATED_SPACE_UUID"
EXPIRES_AT=$(python3 -c 'from datetime import datetime,timedelta,timezone; print((datetime.now(timezone.utc)+timedelta(days=30)).isoformat())')
KEY_RESPONSE=$(curl --fail-with-body -sS -X POST "$ENEO_URL/api/v1/api-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @- <<JSON
{
  "name": "mod-speech-to-text",
  "description": "Service key for the Tal till text module",
  "key_type": "sk_",
  "ownership": "service",
  "permission": "write",
  "scope_type": "space",
  "scope_id": "$SPACE_ID",
  "rate_limit": 1000,
  "expires_at": "$EXPIRES_AT"
}
JSON
)
MODULE_SERVICE_KEY_ID=$(printf '%s' "$KEY_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"]["id"])')
MODULE_SERVICE_KEY=$(printf '%s' "$KEY_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["secret"])')
```

The secret is returned once. Store `MODULE_SERVICE_KEY` as `ENEO_API_KEY` in `env_module_ttt.env`. Preserve `MODULE_SERVICE_KEY_ID` in the operator's secret inventory; it is an identifier used for broker binding and rotation, not a secret.

Use the narrowest documented scope. Prefer a dedicated space, use `write` rather than `admin`, set a realistic rate limit and always set expiration or an appropriate IP policy.

### 4. Bind callback and exchange key

```bash
MODULE_CALLBACK_URL="https://tal-till-text.example.org/api/auth/callback"

curl --fail-with-body -sS -X PATCH \
  "$ENEO_URL/api/v1/modules/$TENANT_ID/$MODULE_DB_ID/client-config/" \
  -H "$API_KEY_HEADER_NAME: $SUPER_DUPER_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @- <<JSON
{
  "redirect_uris": ["$MODULE_CALLBACK_URL"],
  "service_key_id": "$MODULE_SERVICE_KEY_ID"
}
JSON
unset SUPER_DUPER_KEY
```

Redirect matching is normalized and exact. Register each production or test callback explicitly; wildcards are not supported.

### 5. Configure deployment files

Add these values to the project-level `.env`, which Docker Compose reads before service `env_file` entries:

```dotenv
ENEO_DOMAIN=eneo.example.org
MODULE_TTT_DOMAIN=tal-till-text.example.org
MODULE_STT_VERSION=CHANGE_ME_VERIFIED_RELEASE_TAG
```

This repository does not prove that a compatible module image or tag has been published. Replace the placeholder only with an explicit release tag whose compatibility and registry access have been verified for the installed Eneo version; do not use `latest`. Where the module publisher provides a verified image digest, pinning that digest gives stronger immutability than a tag.

Create the module runtime files without overwriting existing ones:

```bash
if [ -e env_modules.env ] || [ -e env_module_ttt.env ]; then
  echo "A module env file already exists; review it instead of overwriting it" >&2
else
  cp env_modules.template env_modules.env
  cp env_module_ttt.template env_module_ttt.env
  chmod 600 env_modules.env env_module_ttt.env
fi
```

Set:

- `ENEO_API_KEY_HEADER_NAME` in `env_modules.env` to the backend's `API_KEY_HEADER_NAME`;
- `TAL_TILL_TEXT_FLOW_ID`, `ENEO_API_KEY` and a generated `SESSION_SECRET` in `env_module_ttt.env`;
- `SESSION_SECRET` to at least 32 random bytes, for example the output of `openssl rand -hex 32`.

The module BFF must pass `ENEO_API_KEY_HEADER_NAME` to `createEneo({ apiKeyHeaderName: ... })`; merely declaring the env variable does not change SDK behavior. The SDK defaults to `X-API-Key` when no override is supplied.

### 6. Validate and start

```bash
docker compose -f docker-compose.yml -f docker-compose.modules.yml \
  --profile speech-to-text config -q

docker compose -f docker-compose.yml -f docker-compose.modules.yml \
  --profile speech-to-text up -d mod-speech-to-text
```

### 7. Verify runtime and login

```bash
# Public health and internal backend reachability.
curl --fail-with-body -sS "https://$MODULE_TTT_DOMAIN/health"
docker exec eneo_mod_speech_to_text wget -q -O- http://backend:8000/version

# Fail explicitly if the diagnostic commands are absent; command-not-found is
# not evidence of isolation.
docker exec eneo_mod_speech_to_text sh -ec '
  command -v getent >/dev/null || { echo "getent is required for this check" >&2; exit 125; }
  command -v wget >/dev/null || { echo "wget is required for this check" >&2; exit 125; }
  ! getent hosts db >/dev/null
  ! getent hosts redis >/dev/null
  ! wget -q --spider -T 5 https://example.com
'
```

Complete the mandatory browser smoke test in a private window:

1. Open the module URL while signed out.
2. Confirm navigation to Eneo `/module-login`, followed by the normal Eneo/IdP login.
3. Confirm return to the exact registered module callback and then to a clean module URL without `ticket` or `state`.
4. Confirm the module has established its own secure session cookie.
5. Execute one resource operation whose backend route itself requires both module credentials; verify that a disabled user, a wrong-tenant token, a revoked service key or a disabled tenant-module assignment is denied on the next request — and that a token refresh is denied under the same conditions. A normal Eneo browser logout alone does not revoke an already minted stateless module token; verify instead that its short expiry bounds the remaining session and that refresh stops working at `session_expires_at`.

Step 5 cannot pass on this branch because the Flow resource routes have not adopted the module dependency. Automate the complete cross-repository flow as a release gate once that runtime exists. Health and diagnostic-session checks alone cannot detect a Flow route that forgot to enforce its authorization dependency.

## Rotate the module key without downtime

The broker accepts the currently bound key and its direct rotation successor. Do not reuse the token or shell variables from initial provisioning: they may be expired or stale. Start a disposable child shell by running `bash`, then run all rotation blocks below in that same child shell. `set -euo pipefail` stops the operation on an unexpected response without changing the parent operator shell.

```bash
set -euo pipefail

ENEO_URL="https://eneo.example.org"
API_KEY_HEADER_NAME="X-API-Key"
TENANT_ID="CHANGE_ME_TENANT_UUID"
MODULE_DB_ID="CHANGE_ME_MODULE_UUID"
MODULE_SERVICE_KEY_ID="CHANGE_ME_CURRENT_KEY_UUID"

printf 'Super-duper key: '
IFS= read -r -s SUPER_DUPER_KEY
printf '\nAdmin email: '
IFS= read -r ADMIN_EMAIL
printf 'Admin password: '
IFS= read -r -s ADMIN_PASSWORD
printf '\n'

TOKEN=$(
  curl --fail-with-body -sS -X POST "$ENEO_URL/api/v1/users/login/token/" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=$ADMIN_EMAIL" \
    --data-urlencode "password=$ADMIN_PASSWORD" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
)
unset ADMIN_PASSWORD
trap 'unset SUPER_DUPER_KEY TOKEN NEW_MODULE_SERVICE_KEY 2>/dev/null || true' EXIT

CURRENT_KEY_RESPONSE=$(curl --fail-with-body -sS \
  "$ENEO_URL/api/v1/api-keys/$MODULE_SERVICE_KEY_ID" \
  -H "Authorization: Bearer $TOKEN")
printf '%s' "$CURRENT_KEY_RESPONSE" |
  python3 -c 'import json,sys; d=json.load(sys.stdin); expected=sys.argv[1]; assert d["id"] == expected and d["state"] == "active", "Current service-key inventory does not point to an active key"' \
  "$MODULE_SERVICE_KEY_ID"

NEW_EXPIRES_AT=$(python3 -c 'from datetime import datetime,timedelta,timezone; print((datetime.now(timezone.utc)+timedelta(days=30)).isoformat())')
ROTATION_RESPONSE=$(curl --fail-with-body -sS -X POST \
  "$ENEO_URL/api/v1/api-keys/$MODULE_SERVICE_KEY_ID/rotate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @- <<JSON
{
  "update_expiration": true,
  "expires_at": "$NEW_EXPIRES_AT",
  "disable_grace_period": false
}
JSON
)
NEW_MODULE_SERVICE_KEY_ID=$(printf '%s' "$ROTATION_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"]["id"])')
NEW_MODULE_SERVICE_KEY=$(printf '%s' "$ROTATION_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["secret"])')
printf '%s' "$ROTATION_RESPONSE" |
  python3 -c 'import json,sys; d=json.load(sys.stdin)["api_key"]; assert d["state"] == "active" and d["rotated_from_key_id"] == sys.argv[1], "Unexpected rotation successor"' \
  "$MODULE_SERVICE_KEY_ID"
```

Then:

1. Replace `ENEO_API_KEY` in `env_module_ttt.env` with `NEW_MODULE_SERVICE_KEY` using the installation's secret-management process.
2. Recreate `mod-speech-to-text` and repeat health plus the full login smoke test while client config still points to the old key ID:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.modules.yml \
     --profile speech-to-text up -d --force-recreate mod-speech-to-text
   ```

3. Only after the new secret works, move the broker binding to the successor ID:

   ```bash
   BINDING_RESPONSE=$(curl --fail-with-body -sS -X PATCH \
     "$ENEO_URL/api/v1/modules/$TENANT_ID/$MODULE_DB_ID/client-config/" \
     -H "$API_KEY_HEADER_NAME: $SUPER_DUPER_KEY" \
     -H "Content-Type: application/json" \
     -d "{\"service_key_id\":\"$NEW_MODULE_SERVICE_KEY_ID\"}")

   printf '%s' "$BINDING_RESPONSE" |
     python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["tenant_id"] == sys.argv[1] and d["module_id"] == sys.argv[2] and d["service_key_id"] == sys.argv[3], "Broker binding was not updated"' \
     "$TENANT_ID" "$MODULE_DB_ID" "$NEW_MODULE_SERVICE_KEY_ID"

   curl --fail-with-body -sS \
     "$ENEO_URL/api/v1/api-keys/$NEW_MODULE_SERVICE_KEY_ID" \
     -H "Authorization: Bearer $TOKEN" |
   python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["state"] == "active", "Successor key is not active"'
   ```

4. Persist `NEW_MODULE_SERVICE_KEY_ID` as the next `MODULE_SERVICE_KEY_ID` in the operator's inventory before the old key's grace period expires. Then run `exit` to leave the disposable shell and clear its secret variables.

Patching client config before the module uses the new secret would immediately reject the old secret despite its API-key grace period. Never skip the client-config PATCH: otherwise a later rotation or purge can break ticket exchange.

## Disable a module

Do not reuse credentials from provisioning or an earlier rotation. Start a fresh disposable child shell by running `bash`, then run the complete block below. It disables ticket issuance first. It attempts both container stop and key revocation even if stop fails; the container is removed only after the key is proven revoked.

```bash
set -euo pipefail

ENEO_URL="https://eneo.example.org"
API_KEY_HEADER_NAME="X-API-Key"
TENANT_ID="CHANGE_ME_TENANT_UUID"
MODULE_DB_ID="CHANGE_ME_MODULE_UUID"
MODULE_SERVICE_KEY_ID="CHANGE_ME_CURRENT_KEY_UUID"
MODULE_KEY="speech-to-text"
MODULE_CALLBACK_URL="https://tal-till-text.example.org/api/auth/callback"

printf 'Super-duper key: '
IFS= read -r -s SUPER_DUPER_KEY
printf '\nAdmin email: '
IFS= read -r ADMIN_EMAIL
printf 'Admin password: '
IFS= read -r -s ADMIN_PASSWORD
printf '\n'

TOKEN=$(
  curl --fail-with-body -sS -X POST "$ENEO_URL/api/v1/users/login/token/" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=$ADMIN_EMAIL" \
    --data-urlencode "password=$ADMIN_PASSWORD" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
)
unset ADMIN_PASSWORD
trap 'unset SUPER_DUPER_KEY TOKEN 2>/dev/null || true' EXIT

ASSIGNMENT_RESPONSE=$(curl --fail-with-body -sS -X DELETE \
  "$ENEO_URL/api/v1/modules/$TENANT_ID/$MODULE_DB_ID/" \
  -H "$API_KEY_HEADER_NAME: $SUPER_DUPER_KEY")
printf '%s' "$ASSIGNMENT_RESPONSE" |
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["tenant_id"] == sys.argv[1] and d["module_id"] == sys.argv[2] and d["enabled"] is False, "Module assignment remains enabled"' \
  "$TENANT_ID" "$MODULE_DB_ID"

stop_failed=0
if ! docker compose -f docker-compose.yml -f docker-compose.modules.yml \
  --profile speech-to-text stop mod-speech-to-text; then
  stop_failed=1
  echo "WARNING: module stop failed; continuing so its service key can still be revoked" >&2
fi

if ! REVOKE_RESPONSE=$(curl --fail-with-body -sS -X POST \
  "$ENEO_URL/api/v1/api-keys/$MODULE_SERVICE_KEY_ID/revoke" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason_code":"admin_action","reason_text":"Module speech-to-text disabled"}'); then
  echo "CRITICAL: service-key revocation failed; do not consider disable complete" >&2
  exit 1
fi
printf '%s' "$REVOKE_RESPONSE" |
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["id"] == sys.argv[1] and d["state"] == "revoked", "Service key was not revoked"' \
  "$MODULE_SERVICE_KEY_ID"

if [ "$stop_failed" -ne 0 ]; then
  echo "The key is revoked, but the module container still requires manual shutdown" >&2
  exit 1
fi

docker compose -f docker-compose.yml -f docker-compose.modules.yml \
  --profile speech-to-text rm -f mod-speech-to-text

DISABLED_STATUS=$(
  curl -sS -o /dev/null -w '%{http_code}' -X POST \
    "$ENEO_URL/api/v1/module-auth/tickets/" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"module_key\":\"$MODULE_KEY\",\"redirect_uri\":\"$MODULE_CALLBACK_URL\",\"state\":\"disable-verification\"}"
)
if [ "$DISABLED_STATUS" != "403" ]; then
  echo "Expected disabled broker to return 403, got $DISABLED_STATUS" >&2
  exit 1
fi

test -z "$(
  docker compose -f docker-compose.yml -f docker-compose.modules.yml \
    --profile speech-to-text ps -q mod-speech-to-text
)"

exit
```

Finally verify that the module health URL is unavailable and that a browser visit through `/module-login` ends at Eneo's generic module-unavailable page. Remove or archive the module env file according to the installation's secret-retention policy.

## Running several modules

- Use one profile, domain, env file, service key and session secret per module.
- Never share service keys between modules.
- Pin every module image independently of the Eneo core version.
- Keep `all-modules` for test installations; select explicit profiles in production.
- Add external API capabilities through Eneo backend APIs rather than giving module containers general internet egress.

## Troubleshooting

**Module container does not become healthy**

Inspect `docker logs eneo_mod_speech_to_text`. Check the pinned image/version, required Flow ID, service-key env name and backend compatibility declared by the module release.

**404 or certificate errors**

Verify `ENEO_DOMAIN` and `MODULE_TTT_DOMAIN` in the project `.env`, DNS, Traefik network labels and certificate resolver.

**Login returns module unavailable**

Verify the exact case-sensitive `speech-to-text` key, targeted tenant assignment, callback URI and client-config service-key ID. Eneo intentionally does not reveal which of these checks failed to the browser.

**Module receives 401/403 from backend**

The service key may be expired, revoked, outside its scope or using the wrong header. Confirm `ENEO_API_KEY_HEADER_NAME`, SDK `apiKeyHeaderName`, key state and Flow/space scope. HTTP 429 means the configured hourly rate limit is too low.

**First rotation works but a later rotation fails**

Client config probably still points at an ancestor key. Patch it to the newly issued key ID after every successful rotation.
