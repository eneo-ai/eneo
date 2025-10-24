# Eneo Frontend

Browser frontend for the Eneo framework, based on SvelteKit.

## Architecture

The frontend consists of two parts, a server that serves the frontend, and the client that runs in the user's browser. The frontend's server handles basic authentication; once authenticated the client can make direct requests to the intric backend, e.g. when uploading files or streaming messages.

```
Intric Backend server <---> Frontend server  <---> Browser / Client
```

## Environment

All deployment specific settings are configured via runtime environment variables. See the sections below (Development, Deployment) to get tips on how to set them for different use cases.

| Variable              | Description                                                                                                           |
| --------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `JWT_SECRET`          | Secret to use when signing JWT tokens on the frontend, used for logging in users.                                     |
| `INTRIC_BACKEND_URL`  | The base url of your Intric backend instance.                                                                         |
| `INTRIC_BACKEND_SERVER_URL` | _Optional._ The url of the Intric backend server, for server-side rendering. Useful when running the backend with the frontend. Defaults to `INTRIC_BACKEND_URL` |
| `MOBILITY_GUARD_AUTH` | _Optional. Required for OIDC/MobilityGuard._ `Authorize` endpoint for the MobilityGuard flow, more info further down. |

### Example config

Your environment could look something like this:

```
JWT_SECRET="abc123"
INTRIC_BACKEND_URL="https://backend.intric.ai:1234"
MOBILITY_GUARD_AUTH="https://example.com/mg-local/intric/oauth2/authorize"
```

## Local Development

Use the vite dev server for local development; setup a `.env` file locally to configure the required environment variables (See the _Environment_ section). You don't need to set `ORIGIN` when working locally.

```bash
# Prepare everything, install and build dependencies
bun -w run setup

# Start vite dev server
bun run dev
```

If you want to work on the client and the UI library at the same time as developing the Web GUI, you should run `bun -w run dev` to run all dev scripts simultaneously.

## OpenId Connect / MobilityGuard

We do support logging in through MobilityGuard. If the `MOBILITY_GUARD_AUTH` environment variable is set, a new login button will appear on the login screen that will handle the MobilityGuard flow. If the variable does not exist this feature is not enabled. For MobilityGuard to work, a user with the exact matching username and the `"created_with": "mobility_guard"` property needs to exist in the intric user table, otherwise the login will fail. Depending on the setup it is also necessary that the mobilityguard operator whitelists our deployment domains as redirect URIs.

The callback URI will always be in the format `https://<deployment>.<tld>/login/callback`, e.g. `https://app.intric.ai/login/callback`

## Formatting

Prettier is configured for this project, ideally you run format on save, or

```bash
bun run format
```

before comitting a file to git.
