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
  onResponse({ request, response }) {
    if (response.status !== 401 || typeof window === "undefined") return;
    // Audit endpoints return 401 to mean "open an access session", not "your
    // session died" — the audit page renders the justification gate from that
    // 401 itself, so reloading here would loop. Everywhere else a 401 means
    // the session is gone: reload so proxy.ts redirects to
    // /login?next=<current page>.
    if (new URL(request.url).pathname.includes("/api/v1/audit/")) return;
    window.location.reload();
  }
});
