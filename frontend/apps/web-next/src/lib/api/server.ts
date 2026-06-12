import "server-only";

import { redirect } from "next/navigation";
import createClient from "openapi-fetch";
import { clearSessionCookie, getAccessToken } from "@/lib/auth/session";
import { env } from "@/lib/env";
import type { paths } from "./schema";

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
    async onResponse({ response }) {
      if (response.status === 401) {
        // The backend rejected a token the session still holds (revoked or
        // expired upstream): the session is dead, start over at login.
        try {
          await clearSessionCookie();
        } catch {
          // RSC render: cookies are read-only here; proxy.ts gates the next
          // request anyway.
        }
        redirect("/login");
      }
    }
  });

  return client;
}
