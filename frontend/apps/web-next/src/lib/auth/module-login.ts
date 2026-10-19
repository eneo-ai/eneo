/**
 * The module login hand-off (`/module-login`), kept pure so the route handler
 * is a thin shell around it. A module sends the browser here with its
 * `module_key`, the `redirect_uri` it registered and a `state` of its own; a
 * signed-in user gets a one-time ticket from the backend
 * (`POST /api/v1/module-auth/tickets/`) and is sent on to the module's
 * `redirect_target`, which is the ticket's only carrier. A signed-out user
 * goes to `/login` with this URL as `next` and comes back afterwards.
 *
 * Same contract as the SvelteKit app's `(public)/module-login/+server.ts`.
 */

export const MODULE_LOGIN_PATH = "/module-login";
export const MODULE_LOGIN_FAILED_PATH = "/module-login/failed";

/** Every response of the hand-off, the login redirect included, carries these. */
export const MODULE_LOGIN_RESPONSE_HEADERS = {
  "Cache-Control": "private, no-store, max-age=0",
  "Referrer-Policy": "no-referrer",
  "X-Robots-Tag": "noindex, nofollow, noarchive"
} as const;

export const MODULE_LOGIN_FAILURE_REASONS = [
  "invalid_request",
  "module_unavailable",
  "service_unavailable"
] as const;

export type ModuleLoginFailureReason = (typeof MODULE_LOGIN_FAILURE_REASONS)[number];

/** The `?reason=` the failed page received, defaulting to the generic one. */
export function moduleLoginFailureReason(raw: unknown): ModuleLoginFailureReason {
  return typeof raw === "string" &&
    (MODULE_LOGIN_FAILURE_REASONS as readonly string[]).includes(raw)
    ? (raw as ModuleLoginFailureReason)
    : "invalid_request";
}

export type ModuleLoginRequest = {
  moduleKey: string;
  redirectUri: string;
  state: string;
};

const REQUEST_PARAMETERS = new Set(["module_key", "redirect_uri", "state"]);

function exactlyOneNonEmpty(searchParams: URLSearchParams, name: string): string | null {
  const values = searchParams.getAll(name);
  if (values.length !== 1 || values[0]!.trim().length === 0) return null;
  return values[0]!;
}

/**
 * The three request parameters, each exactly once and non-blank, and nothing
 * else in the query. Anything else is an invalid request.
 */
export function parseModuleLoginRequest(searchParams: URLSearchParams): ModuleLoginRequest | null {
  for (const name of searchParams.keys()) {
    if (!REQUEST_PARAMETERS.has(name)) return null;
  }
  const moduleKey = exactlyOneNonEmpty(searchParams, "module_key");
  const redirectUri = exactlyOneNonEmpty(searchParams, "redirect_uri");
  const state = exactlyOneNonEmpty(searchParams, "state");
  if (moduleKey === null || redirectUri === null || state === null) return null;
  return { moduleKey, redirectUri, state };
}

/** Where the hand-off resumes after login: this URL, parameters included. */
export function moduleLoginResumePath(url: URL): string {
  return url.pathname + url.search;
}

/** `/login?next=<resume path>`, as a path on this origin. */
export function loginPathToResume(resumePath: string): string {
  return `/login?${new URLSearchParams({ next: resumePath })}`;
}

export function moduleLoginFailurePath(reason: ModuleLoginFailureReason): string {
  return `${MODULE_LOGIN_FAILED_PATH}?reason=${reason}`;
}

export type TicketOutcome =
  /** The backend rejected the session: sign in again and come back. */
  | { kind: "login" }
  | { kind: "failure"; reason: ModuleLoginFailureReason }
  /** 2xx: the body carries the module's `redirect_target`. */
  | { kind: "issued" };

/** What the ticket endpoint's status means for the browser. */
export function ticketOutcome(status: number): TicketOutcome {
  if (status === 401) return { kind: "login" };
  if (status === 422) return { kind: "failure", reason: "invalid_request" };
  if (status === 400 || status === 403 || status === 404) {
    return { kind: "failure", reason: "module_unavailable" };
  }
  if (status < 200 || status >= 300) return { kind: "failure", reason: "service_unavailable" };
  return { kind: "issued" };
}

/**
 * The backend-generated redirect target, accepted only as an http(s) URL
 * without credentials, and returned exactly as received: the ticket rides on
 * it, so it is never normalised or reconstructed.
 */
export function validatedRedirectTarget(value: unknown): string | null {
  if (typeof value !== "string" || value.length === 0) return null;
  try {
    const target = new URL(value);
    if (
      (target.protocol !== "https:" && target.protocol !== "http:") ||
      target.username.length > 0 ||
      target.password.length > 0
    ) {
      return null;
    }
  } catch {
    return null;
  }
  return value;
}

/** The `redirect_target` of a ticket response body, validated. */
export function redirectTargetFromBody(body: unknown): string | null {
  return validatedRedirectTarget(
    typeof body === "object" && body !== null && "redirect_target" in body
      ? body.redirect_target
      : null
  );
}
