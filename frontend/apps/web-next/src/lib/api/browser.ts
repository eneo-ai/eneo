import createClient, { type Client } from "openapi-fetch";
import { errorCodeFromResponse } from "./errors";
import type { paths } from "./schema";
import { passwordChangeUrl } from "@/lib/auth/password-change-path";

/** A typed Eneo API client, regardless of transport (direct or proxied). */
export type EneoClient = Client<paths>;

/**
 * Typed client for client components. The browser never holds a backend
 * token: requests go to the same-origin /api/eneo proxy route, which swaps
 * the session cookie for a bearer header. Paths keep their full /api/v1/...
 * shape, so a request becomes e.g. /api/eneo/api/v1/dashboard/.
 */
export const browserApi: EneoClient = createClient<paths>({ baseUrl: "/api/eneo" });

const PASSWORD_CHANGE_REQUIRED = 9070;

browserApi.use({
  async onResponse({ request, response }) {
    if (typeof window === "undefined") return;
    if (response.status === 403) {
      // The session must replace its local password before anything else;
      // the server client sends renders there too (see server.ts).
      if ((await errorCodeFromResponse(response)) === PASSWORD_CHANGE_REQUIRED) {
        window.location.assign(
          passwordChangeUrl(window.location.pathname + window.location.search)
        );
      }
      return;
    }
    if (response.status !== 401) return;
    // Audit endpoints return 401 to mean "open an access session", not "your
    // session died" — the audit page renders the justification gate from that
    // 401 itself, so reloading here would loop. Everywhere else a 401 means
    // the session is gone: reload so proxy.ts redirects to
    // /login?next=<current page>.
    if (new URL(request.url).pathname.includes("/api/v1/audit/")) return;
    window.location.reload();
  }
});
