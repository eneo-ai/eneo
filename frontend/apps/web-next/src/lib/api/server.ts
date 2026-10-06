import "server-only";

import { redirect } from "next/navigation";
import createClient from "openapi-fetch";
import { getAccessToken } from "@/lib/auth/session";
import { env } from "@/lib/env";
import { errorCodeFromResponse } from "./errors";
import type { paths } from "./schema";

const USER_NOT_CREATED = 9006;
const TENANT_SUSPENDED = 9025;

/**
 * Typed backend client for server components, route handlers and server
 * actions. Talks to the backend directly (ENEO_BACKEND_URL) with the
 * session's bearer token injected per request.
 *
 * Pair with unwrap() from ./errors to throw EneoApiError on failure:
 *
 *   const dashboard = await unwrap(eneoApi().GET("/api/v1/dashboard/"));
 */
export function eneoApi() {
  const client = createClient<paths>({ baseUrl: env.ENEO_BACKEND_URL });

  client.use({
    async onRequest({ request }) {
      request.headers.set("Authorization", `Bearer ${await getAccessToken()}`);
      return request;
    },
    async onResponse({ request, response }) {
      if (response.status !== 401 && response.status !== 403) return;
      // The activate page owns provision failures — don't intercept them.
      if (new URL(request.url).pathname.endsWith("/api/v1/users/provision/")) return;

      if (response.status === 401) {
        const code = await errorCodeFromResponse(response);
        // Authenticated at the IdP but no Eneo account (JIT provisioning off):
        // the activate page offers manual provisioning.
        if (code === USER_NOT_CREATED) redirect("/activate");
        // The backend rejected a token the session still holds (revoked or
        // expired upstream). Cookies are read-only during RSC render, so the
        // logout route clears the session — redirecting straight to /login
        // would bounce back here forever off the still-valid cookie.
        redirect("/logout?reason=expired");
      }

      if ((await errorCodeFromResponse(response)) === TENANT_SUSPENDED) {
        redirect("/deactivated");
      }
    }
  });

  return client;
}
