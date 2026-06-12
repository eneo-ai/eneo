import createClient, { type Client } from "openapi-fetch";
import type { paths } from "./schema";

/** A typed Eneo API client, regardless of transport (direct or proxied). */
export type EneoClient = Client<paths>;

/**
 * Typed client for client components. The browser never holds a backend
 * token: requests go to the same-origin /api/eneo proxy route, which swaps
 * the session cookie for a bearer header. Paths keep their full /api/v1/...
 * shape, so a request becomes e.g. /api/eneo/api/v1/dashboard/.
 */
export const browserApi: EneoClient = createClient<paths>({ baseUrl: "/api/eneo" });

browserApi.use({
  onResponse({ response }) {
    if (response.status === 401 && typeof window !== "undefined") {
      // Session expired or gone: reload the page so proxy.ts redirects to
      // /login?next=<current page> and login can return here.
      window.location.reload();
    }
  }
});
