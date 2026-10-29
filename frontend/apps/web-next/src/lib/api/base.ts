import { errorCodeFromResponse } from "./errors";
import { passwordChangeUrl } from "@/lib/auth/password-change-path";

/**
 * Where the browser sends its backend requests, and what it does with a
 * refusal: the one place the Next and Vite builds differ. This is the Next
 * build's module; the Vite build swaps in base.vite.ts with a resolve alias
 * (Vitest resolves this one).
 *
 * In Next the browser never holds a backend token: requests go to the
 * same-origin /api/eneo proxy route, which swaps the session cookie for a
 * bearer header. Paths keep their full /api/v1/... shape, so a request
 * becomes e.g. /api/eneo/api/v1/dashboard/.
 */
export const API_BASE = "/api/eneo";
/** The chat stream: Next's proxy route in front of the v3 conversations endpoint. */
export const CHAT_API = "/api/chat";
/** The signed-in user's job feed: Next's proxy route in front of the backend's. */
export const JOB_EVENTS_PATH = "/api/jobs/events";

/** Request preparation is specific to Vite's cookie session contract. */
export async function onBrowserApiRequest({ request }: { request: Request }): Promise<Request> {
  return request;
}

export const apiFetch: typeof fetch = (input, init) => fetch(input, init);

export type ApiEventSource = {
  readonly readyState: number;
  addEventListener(type: string, listener: (event: Event) => void): void;
  close(): void;
};

export function createApiEventSource(url: string): ApiEventSource {
  return new EventSource(url);
}

const PASSWORD_CHANGE_REQUIRED = 9070;

/** The typed browser client's response middleware (browser.ts). */
export async function onBrowserApiResponse({
  request,
  response
}: {
  request: Request;
  response: Response;
}): Promise<void> {
  if (typeof window === "undefined") return;
  if (response.status === 403) {
    // The session must replace its local password before anything else;
    // the server client sends renders there too (see server.ts).
    if ((await errorCodeFromResponse(response)) === PASSWORD_CHANGE_REQUIRED) {
      window.location.assign(passwordChangeUrl(window.location.pathname + window.location.search));
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

/**
 * XHR response checks use the same Vite session owner as fetch. Next keeps
 * its existing local upload errors until the proxy is removed.
 */
export const onRawRefusal: (
  response: Response,
  requestUrl: string
) => Promise<void> = async () => {};
