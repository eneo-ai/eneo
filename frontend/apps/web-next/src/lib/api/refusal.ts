import { apiErrorFromResponse, EneoApiError } from "./errors";
import { getQueryClient } from "./query";
import type { components } from "./schema";
import { loginPathToResume } from "@/lib/auth/module-login";
import { passwordChangeUrl } from "@/lib/auth/password-change-path";
import { safeNextPath } from "@/lib/auth/safe-next";
import { navigateTo } from "@/lib/navigate-to";

export const SESSION_GENERATION_HEADER = "Eneo-Session-Generation";
const SESSION_PROBE = "/api/v1/auth/session/";
const SESSION_EXTEND = "/api/v1/auth/session/extend/";
/** Whole seconds the session has left, on the probe. */
const SESSION_EXPIRES_IN_HEADER = "Eneo-Session-Expires-In";
/** Whole seconds the session was issued for, on the probe; older servers omit it. */
const SESSION_LIFETIME_HEADER = "Eneo-Session-Lifetime";
/** Tabs of this browser share the cookie; a renewal in one is announced here. */
const SESSION_CHANNEL = "eneo-session";
/** Never a credential: which session was renewed (it keeps its generation) and when it now ends. */
type Renewal = { generation: string; expiresAt: number };
const SESSION_MISMATCH = 9090;
/** Refusals of the identity itself: an inactive account, a suspended organisation. */
const RESTRICTIONS = [9019, 9025] as const;
export type Restriction = (typeof RESTRICTIONS)[number];
const restrictionOf = (code: number | undefined): Restriction | undefined =>
  RESTRICTIONS.find((restriction) => restriction === code);

export type SessionSnapshot =
  | { status: "unbound" }
  | {
      status: "bound";
      generation: string | null;
      logoutGeneration?: string;
      checkError?: unknown;
      /** When the session ends (ms since epoch), from the last check or renewal. */
      expiresAt?: number;
      /** How long the session was issued for (ms), when the server says. */
      lifetime?: number;
    }
  | { status: "deactivated"; generation: string; restriction: Restriction }
  | { status: "stale"; destination: string; restriction?: Restriction };

let snapshot: SessionSnapshot = { status: "unbound" };
let pendingProbe: Promise<void> | undefined;
/** Renewals this document has followed, its own and other tabs'. */
let renewals = 0;
const requests = new AbortController();
const listeners = new Set<() => void>();

export const getSessionSnapshot = (): SessionSnapshot => snapshot;
export const getSessionSignal = (): AbortSignal => requests.signal;
export function subscribeSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function publish(next: SessionSnapshot): void {
  snapshot = next;
  listeners.forEach((listener) => listener());
}

function staleError(): EneoApiError {
  return new EneoApiError("The browser session changed after this page was loaded.", {
    status: 401,
    code: SESSION_MISMATCH
  });
}

function assertCurrent(): void {
  if (snapshot.status === "stale") throw staleError();
  if (snapshot.status === "deactivated") {
    throw new EneoApiError(
      snapshot.restriction === 9019
        ? "The account is inactive."
        : "The organisation is deactivated.",
      { status: 403, code: snapshot.restriction }
    );
  }
}

function publicAuthPage(): boolean {
  const pathname = window.location.pathname;
  return ["/login", "/logout", "/deactivated", "/password-change", "/module-login"].some(
    (prefix) => pathname === prefix || pathname.startsWith(prefix + "/")
  );
}

function resumePath(): string {
  // The fragment too: safeNextPath keeps it, so a section link survives sign-in.
  return safeNextPath(window.location.pathname + window.location.search + window.location.hash);
}

/** Sign-in that returns to this page. */
export function resumeLoginPath(): string {
  return loginPathToResume(resumePath());
}
// Another sign-in now holds the cookie. The page cannot know whose it is, so it
// never resumes its own deep link (another person's conversation, say).
const REPLACED_SESSION_DESTINATION = "/login";

function makeStale(
  destination = resumeLoginPath(),
  error = staleError(),
  restriction?: Restriction
): never {
  if (snapshot.status !== "stale") {
    // Publish before navigation: beforeunload may cancel the document load.
    publish({ status: "stale", destination, ...(restriction ? { restriction } : {}) });
    requests.abort(new DOMException("The browser session changed", "AbortError"));
    const queryClient = getQueryClient();
    void queryClient.cancelQueries();
    queryClient.clear();
    // Replace this entry: Back would reload the page only to be sent here again,
    // so the person could never go Back past Eneo.
    if (!publicAuthPage()) navigateTo(destination, { replace: true });
  }
  throw error;
}

/** The explicit retry keeps the document blocked until a new document loads. */
export function reloadSession(): void {
  if (snapshot.status === "stale") navigateTo(snapshot.destination, { replace: true });
}

/** Check headers before a response body reaches a cache or stream consumer. */
export const handleRefusal: (response: Response, requestUrl: string) => Promise<void> = async (
  response
) => {
  checkAnswerSession(response);
  if (response.status !== 401 && response.status !== 403) return;
  applyRefusal(response, await refusalOf(response));
};

/** The answer must speak for this document's session; a success must say which. */
function checkAnswerSession(response: Response): void {
  assertCurrent();
  const generation = response.headers.get(SESSION_GENERATION_HEADER);
  if (snapshot.status === "bound" && generation !== null && generation !== snapshot.generation) {
    makeStale(snapshot.generation === null ? undefined : REPLACED_SESSION_DESTINATION);
  }
  if (response.ok && generation === null) {
    throw new EneoApiError("The API response did not identify its browser session.", {
      status: 502
    });
  }
}

/** Why the server refused, read from a copy so the body stays for its consumer. */
async function refusalOf(response: Response): Promise<EneoApiError> {
  let body: unknown;
  try {
    body = await response.clone().json();
  } catch {
    body = undefined;
  }
  return apiErrorFromResponse(response, body);
}

/** What a 401 or 403 does to the document, once its reason is known. */
function applyRefusal(response: Response, error: EneoApiError): void {
  assertCurrent();
  if (error.code === SESSION_MISMATCH) makeStale(REPLACED_SESSION_DESTINATION, error);
  const restriction = response.status === 403 ? restrictionOf(error.code) : undefined;
  if (restriction) makeStale("/deactivated", error, restriction);
  if (response.status === 403 && error.code === 9070)
    makeStale(passwordChangeUrl(resumePath()), error);
  if (publicAuthPage()) return;
  if (response.status === 401) {
    const auditCode = response.headers.get("X-Error-Code");
    if (auditCode === "AUDIT_SESSION_REQUIRED" || auditCode === "AUDIT_SESSION_EXPIRED") return;
    makeStale(undefined, error);
  }
}

/** Cookie requests and cache-only route gates share this document's session check. */
export async function requireBrowserSession(): Promise<string> {
  if (pendingProbe) await pendingProbe;
  assertCurrent();
  if (snapshot.status === "unbound") {
    throw new EneoApiError("The browser session has not been checked.", { status: 503 });
  }
  if (snapshot.status !== "bound") throw staleError();
  if (snapshot.checkError !== undefined) throw snapshot.checkError;
  if (snapshot.generation === null) {
    // An anonymous document must not adopt a cookie set by another tab.
    if (!publicAuthPage()) makeStale();
    throw new EneoApiError("No browser session", { status: 401 });
  }
  return snapshot.generation;
}

/** Every cookie transport uses this before sending, including XHR uploads. */
export async function prepareBrowserRequest(request: Request): Promise<Request> {
  const generation = await requireBrowserSession();
  const headers = new Headers(request.headers);
  headers.set(SESSION_GENERATION_HEADER, generation);
  return new Request(request, {
    headers,
    signal: AbortSignal.any([request.signal, requests.signal])
  });
}

/** Bootstrap is identity-free until this one response binds the document. */
export function initializeBrowserSession(): Promise<void> {
  if (snapshot.status !== "unbound") return Promise.resolve();
  return checkBrowserSession().catch((error: unknown) => {
    // Render the blocking state if initial navigation could not leave.
    if (snapshot.status !== "stale" && snapshot.status !== "deactivated") throw error;
  });
}

/** Coalesce resume checks and hold new work until the check has succeeded. */
export function checkBrowserSession(): Promise<void> {
  if (pendingProbe) return pendingProbe;
  const work = probeSession();
  pendingProbe = work;
  void work
    .finally(() => {
      // A renewal may have taken over the hold while this check ran.
      if (pendingProbe === work) pendingProbe = undefined;
    })
    .catch(() => {});
  return work;
}

async function probeSession(): Promise<void> {
  assertCurrent();
  const before = snapshot;
  const renewalsBefore = renewals;
  // Another tab renewed while this check was out: the check's answer may be
  // about the token that renewal replaced (its end, or its expiry).
  const superseded = () => snapshot.status === "bound" && renewals !== renewalsBefore;
  const headers = new Headers();
  const expected =
    before.status === "bound" ? (before.generation ?? before.logoutGeneration) : undefined;
  if (expected) {
    headers.set(SESSION_GENERATION_HEADER, expected);
  }
  try {
    // Deliberately native fetch: this is the check that prepares other requests.
    const response = await fetch(SESSION_PROBE, {
      headers,
      cache: "no-store",
      credentials: "same-origin",
      signal: requests.signal
    });
    // Reading why it was refused is the last wait. Nothing is applied before
    // it, so a renewal adopted while the answer arrived is never undone.
    const refused = response.status === 204 ? undefined : await refusalOf(response);
    assertCurrent();
    if (superseded()) return;
    let generation: string | null;
    let logoutGeneration: string | undefined;
    let expiresAt: number | undefined;
    let lifetime: number | undefined;
    if (!refused) {
      generation = response.headers.get(SESSION_GENERATION_HEADER);
      if (!generation)
        throw new EneoApiError("The session probe returned no generation.", { status: 502 });
      // Relative to now, so this device's clock cannot move the deadline.
      const left = seconds(response.headers.get(SESSION_EXPIRES_IN_HEADER));
      if (left !== undefined) expiresAt = Date.now() + left;
      lifetime = seconds(response.headers.get(SESSION_LIFETIME_HEADER));
    } else if (response.status === 401) {
      if (refused.code === SESSION_MISMATCH) makeStale(REPLACED_SESSION_DESTINATION);
      generation = null;
      // An expired cookie still needs a binding for logout. It never grants
      // authenticated reads or lets this document adopt a later session.
      logoutGeneration = response.headers.get(SESSION_GENERATION_HEADER) ?? undefined;
    } else {
      const restriction =
        before.status === "unbound" && response.status === 403
          ? restrictionOf(refused.code)
          : undefined;
      if (restriction) {
        // No identity was admitted. Only public recovery may render; retrying
        // starts a new document, just as recovering a stale bound session does.
        const generation = response.headers.get(SESSION_GENERATION_HEADER);
        if (!generation)
          throw new EneoApiError("The session probe returned no generation.", { status: 502 });
        publish({ status: "deactivated", generation, restriction });
        if (!["/deactivated", "/logout"].includes(window.location.pathname)) {
          navigateTo("/deactivated", { replace: true });
        }
        return;
      }
      checkAnswerSession(response);
      if (response.status === 403) applyRefusal(response, refused);
      throw refused;
    }
    if (
      before.status === "bound" &&
      (before.generation !== generation || before.logoutGeneration !== logoutGeneration)
    )
      // Expiry or sign-out (no generation now) resumes the page; another credential does not.
      makeStale(
        before.generation !== null && generation !== null ? REPLACED_SESSION_DESTINATION : undefined
      );
    publish({
      status: "bound",
      generation,
      ...(logoutGeneration ? { logoutGeneration } : {}),
      ...(expiresAt !== undefined ? { expiresAt } : {}),
      ...(lifetime !== undefined ? { lifetime } : {})
    });
  } catch (error) {
    if (superseded()) return;
    if (snapshot.status === "bound") publish({ ...snapshot, checkError: error });
    throw error;
  }
}

/** Whole seconds in a header, as ms. */
function seconds(header: string | null): number | undefined {
  return header !== null && /^\d+$/.test(header) ? Number(header) * 1000 : undefined;
}

/** A renewed session: its token was just issued, so what it has left is its lifetime. */
const renewedSession = (expiresAt: number) => ({ expiresAt, lifetime: expiresAt - Date.now() });

let channel: BroadcastChannel | undefined;
function sessionChannel(): BroadcastChannel | undefined {
  if (typeof BroadcastChannel === "undefined") return undefined;
  return (channel ??= new BroadcastChannel(SESSION_CHANNEL));
}

/**
 * Renew this document's session before it ends. It keeps its generation, so
 * nothing else changes but when it ends. Requests wait for it as for a
 * session check; other tabs bound to the same session follow the new end.
 */
export function extendBrowserSession(): Promise<void> {
  const seen = renewals;
  const previous = pendingProbe;
  const renew = () => renewSession(seen);
  const work = (async () => {
    await previous?.catch(() => {});
    // One tab at a time; a tab that waited may find the session renewed.
    await ("locks" in navigator ? navigator.locks.request("eneo-session-extend", renew) : renew());
  })();
  pendingProbe = work;
  void work
    .finally(() => {
      if (pendingProbe === work) pendingProbe = undefined;
    })
    .catch(() => {});
  return work;
}

async function renewSession(seen: number): Promise<void> {
  assertCurrent();
  if (snapshot.status !== "bound" || !snapshot.generation) {
    throw new EneoApiError("No browser session", { status: 401 });
  }
  if (renewals !== seen) return;
  const { generation } = snapshot;
  // A refusal ends the document as any refusal does. A lost answer keeps the
  // page as it was: renewed or not, the cookie is still this page's session
  // (a renewal keeps its generation), so the next request works and Retry
  // renews again.
  // Native, like the probe.
  const response = await fetch(SESSION_EXTEND, {
    method: "POST",
    headers: { [SESSION_GENERATION_HEADER]: generation },
    cache: "no-store",
    credentials: "same-origin",
    signal: requests.signal
  });
  assertCurrent();
  if (!response.ok) {
    await handleRefusal(response, SESSION_EXTEND);
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = undefined;
    }
    throw apiErrorFromResponse(response, body);
  }
  const body = (await response.json()) as components["schemas"]["BrowserSessionExtension"];
  const renewal: Renewal = { generation, expiresAt: Date.now() + body.expires_in * 1000 };
  renewals += 1;
  publish({ status: "bound", generation, ...renewedSession(renewal.expiresAt) });
  sessionChannel()?.postMessage(renewal);
}

/** The root owns this subscription's lifetime; StrictMode can mount it again. */
export function listenForSessionResume(): () => void {
  const check = () => {
    void checkBrowserSession().catch(() => {});
  };
  const visible = () => {
    if (document.visibilityState === "visible") check();
  };
  const restored = (event: PageTransitionEvent) => {
    if (event.persisted) check();
  };
  // Capture precedes query/feature listeners on document, so their requests
  // join the pending check even when those listeners were registered first.
  // Another tab renewed the cookie: follow it only for this document's session.
  const renewed = ({ data }: MessageEvent<Partial<Renewal>>) => {
    if (
      snapshot.status === "bound" &&
      snapshot.generation !== null &&
      snapshot.generation === data.generation &&
      typeof data.expiresAt === "number"
    ) {
      renewals += 1;
      publish({ ...snapshot, ...renewedSession(data.expiresAt) });
    }
  };
  window.addEventListener("visibilitychange", visible, true);
  window.addEventListener("pageshow", restored, true);
  sessionChannel()?.addEventListener("message", renewed);
  return () => {
    window.removeEventListener("visibilitychange", visible, true);
    window.removeEventListener("pageshow", restored, true);
    sessionChannel()?.removeEventListener("message", renewed);
  };
}
