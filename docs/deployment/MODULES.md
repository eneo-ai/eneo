# Eneo Modules — installation and operations guide

Modules are optional web applications deployed next to Eneo. A module has its
own BFF, browser session and domain, and calls Eneo through published APIs. The
Eneo admin interface owns installation and authentication configuration; DNS,
containers and module secrets remain operator responsibilities.

There is no separate module-management environment key. Administrators use
their ordinary Eneo session and the `modules` permission. Eneo derives the
organization from that session, so neither the interface nor the admin API
accepts a tenant ID.

## What the configuration means

An installed module consists of three values:

- **Module key:** the stable, case-sensitive machine identity shared by Eneo
  and the module runtime, for example `speech-to-text`. Use letters and digits
  plus `.`, `_` or `-`; the first character must be a letter or digit. Treat the
  key as immutable.
- **Callback URLs:** the exact HTTPS endpoints to which Eneo may return a
  one-time login ticket. Wildcards are not supported. Register production and
  test callbacks separately.
- **Service key:** an active `sk_` key owned by a service with `write` or
  `admin` permission and the narrowest resource scope the module needs. The
  module BFF stores its secret; Eneo stores only the key ID used to bind ticket
  exchange to that module.

Eneo keeps tenant IDs internally as data-partition keys. This is deliberate:
the current product flow configures modules for the organization of the signed
in administrator without presenting tenant support as a user-facing concept.

## Install a module in the admin interface

Before starting, deploy or obtain a module release that explicitly supports
Eneo's module-auth handoff. A healthy container alone does not prove that login
or resource authorization works.

1. Sign in with a role containing `admin`, `modules` and `api_keys`. The
   predefined Owner role contains these permissions.
2. Open **Administration → API keys** and create a key with:

   - type `sk_`;
   - ownership `service`;
   - the narrowest resource scope the module needs (often a dedicated space);
   - permission `write` (use `admin` only when the module contract requires it);
   - an expiration and rate limit appropriate for the module.

3. Copy the secret immediately to the module's secret store. It is shown only
   once. Do not put it in browser code, source control or the general Eneo web
   environment.
4. Open **Administration → Modules**.
5. Enter the module key, one exact callback URL per line and select the service
   key. Choose **Install module**.
6. Configure the same module key and service-key secret in the module runtime,
   then start or recreate its container.

The save operation is atomic and idempotent: Eneo validates the service key,
registers the stable module identity, enables it for the current organization
and writes the complete callback/key binding in one transaction. A failed
validation does not leave a half-installed module.

Existing installations appear in the same page. Choose **Edit** to replace the
complete callback/key configuration. The module key is immutable.

## Admin API alternative

Automation may use the same tenant-implicit contract with a normal user Bearer
token. Do not send an environment key or tenant ID.

```bash
ENEO_URL="https://eneo.example.org"
MODULE_KEY="speech-to-text"
MODULE_CALLBACK_URL="https://tal-till-text.example.org/api/auth/callback"
MODULE_SERVICE_KEY_ID="CHANGE_ME_KEY_UUID"

printf 'Administrator Bearer token: '
IFS= read -r -s TOKEN
printf '\n'

curl --fail-with-body -sS -X PUT \
  "$ENEO_URL/api/v1/admin/modules/$MODULE_KEY/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @- <<JSON
{
  "redirect_uris": ["$MODULE_CALLBACK_URL"],
  "service_key_id": "$MODULE_SERVICE_KEY_ID"
}
JSON

curl --fail-with-body -sS \
  "$ENEO_URL/api/v1/admin/modules/" \
  -H "Authorization: Bearer $TOKEN"

unset TOKEN
```

The API exposes only these lifecycle operations:

- `GET /api/v1/admin/modules/` — list installations for the signed-in user's
  organization;
- `PUT /api/v1/admin/modules/{module_key}/` — install or completely
  reconfigure one module;
- `DELETE /api/v1/admin/modules/{module_key}/` — uninstall one module.

## Module login and request authorization

Modules do not register separate identity-provider clients. Eneo remains the
installation's OIDC client:

1. The module generates an unpredictable, one-time `state`, binds it to the
   browser and navigates to Eneo `/module-login` with `module_key`,
   `redirect_uri` and `state`.
2. Eneo uses the existing session or completes normal login, verifies access
   and redirects to the configured callback with a short-lived ticket and the
   unchanged `state`.
3. The module verifies and consumes `state`, exchanges the ticket server-side
   using its bound service key and creates its own secure session.

The callback must use an `HttpOnly`, `Secure`, `SameSite=Lax` state cookie,
reject missing/reused/mismatched state before exchange, set
`Referrer-Policy: no-referrer`, and redirect immediately to a clean URL without
ticket or state query parameters.

Every protected module resource request must send both credentials:

- the bound service key in Eneo's configured API-key header (default
  `X-API-Key`); and
- the module-user Bearer token.

The backend resource route itself must apply
`require_module_request(<server-owned-module-key>)`. The module BFF and the
diagnostic session route are not substitutes for resource authorization.
Disabling the user, organization, service key or module assignment then takes
effect on the next request.

The ticket is single-use and short-lived. Redis 6.2 or newer is required for
atomic consumption; the bundled stack uses Redis 7.

## Session refresh

The exchanged module token is short-lived (`MODULE_AUTH_TOKEN_EXPIRY_MINUTES`,
default 60). `session_expires_at` is an absolute ceiling from the original
handoff (`MODULE_AUTH_MAX_SESSION_HOURS`, default 8).

Refresh through
`POST /api/v1/module-auth/{module_key}/token/refresh/` using both the current
Bearer token and bound service key. Refresh rechecks live user, organization,
key and module state, and never extends beyond the original ceiling. On `401`
or `403`, end the module session and restart handoff.

## Deployment boundary

The admin interface intentionally does not start containers or configure DNS.
After saving the Eneo configuration:

1. point the module domain at the Eneo ingress;
2. pin a module release known to support the installed Eneo version (avoid
   `latest`; prefer a verified digest when available);
3. store the copied service-key secret and a separately generated module
   session secret in the module runtime;
4. set the runtime's `MODULE_KEY` to the exact installed key;
5. validate the compose overlay, start the module and check health.

The module BFF must pass the backend's header name to
`createEneo({ apiKeyHeaderName: ... })` if it differs from `X-API-Key`.

## Required smoke test

Use a private browser window:

1. Open the module while signed out.
2. Confirm navigation through Eneo `/module-login` and the normal IdP login.
3. Confirm return to the exact registered callback and then a clean module URL.
4. Confirm the module created its own secure session cookie.
5. Execute a real protected resource operation. Verify that a disabled user, a
   wrong-organization token, a revoked service key and an uninstalled module
   are each denied on the next request and on refresh.

Health and `GET /api/v1/module-auth/{module_key}/session/` checks alone cannot
detect a resource route that forgot its authorization dependency.

## Rotate a module service key

1. In **Administration → API keys**, rotate the current service key and copy
   the successor secret.
2. Replace the secret in the module runtime and recreate the module container.
3. Run the full login and protected-resource smoke test while the current
   binding and key rotation grace allow it.
4. In **Administration → Modules**, edit the module, select the successor key
   and save the complete configuration.
5. Verify login again, then allow the old key's grace period to end or revoke
   it according to the incident/runbook policy.

Do not bind the successor before the module runtime uses its secret: the module
would immediately lose ticket-exchange access.

## Uninstall a module

1. In **Administration → Modules**, choose **Remove** and confirm. Ticket
   issuance stops and the callback/key binding is deleted atomically.
2. Stop the module container.
3. Revoke its service key in **Administration → API keys**. Key revocation is a
   separate lifecycle action because a key may have incident and audit policy
   beyond module installation.
4. Remove the container only after shutdown and revocation are verified.

For automation, use:

```bash
curl --fail-with-body -sS -X DELETE \
  "$ENEO_URL/api/v1/admin/modules/$MODULE_KEY/" \
  -H "Authorization: Bearer $TOKEN"
```

## Troubleshooting

- **Module page is missing:** the user needs both access to Administration and
  the `modules` permission. Owner receives it by default; custom roles must be
  updated explicitly.
- **No service key can be selected:** create an active service-owned `sk_` key
  with `write` or `admin` permission.
- **Save returns 400:** verify that the key is active, belongs to the current
  organization and meets the ownership/scope/permission requirements.
- **Login returns 404/403:** verify the exact case-sensitive module key and that
  the module remains installed.
- **Redirect is rejected:** compare scheme, host, port, path and trailing slash
  with the saved callback. Matching is exact after normalization.
- **Ticket exchange returns 401:** verify the module runtime uses the secret of
  the key currently selected on the Modules page and that the key is active.
- **Session or refresh returns 403:** the key may be valid but no longer bound
  to that installed module.
