import { apiErrorFromResponse, EneoApiError, errorCodeFromResponse } from "./errors";
import { getQueryClient } from "./query";
import { loginPathToResume } from "@/lib/auth/module-login";
import { passwordChangeUrl } from "@/lib/auth/password-change-path";
import { safeNextPath } from "@/lib/auth/safe-next";
import { navigateTo } from "@/lib/navigate-to";

export const SESSION_GENERATION_HEADER = "Eneo-Session-Generation";
const SESSION_PROBE = "/api/v1/auth/session/";
const SESSION_MISMATCH = 9090;
/** Refusals of the identity itself: an inactive account, a suspended organisation. */
const RESTRICTIONS = [9019, 9025] as const;
export type Restriction = (typeof RESTRICTIONS)[number];
const restrictionOf = (code: number | undefined): Restriction | undefined =>
  RESTRICTIONS.find((restriction) => restriction === code);

export type SessionSnapshot =
  | { status: "unbound" }
  | { status: "bound"; generation: string | null; logoutGeneration?: string; checkError?: unknown }
  | { status: "deactivated"; generation: string; restriction: Restriction }
  | { status: "stale"; destination: string; restriction?: Restriction };

let snapshot: SessionSnapshot = { status: "unbound" };
let pendingProbe: Promise<void> | undefined;
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
  return safeNextPath(window.location.pathname + window.location.search);
}

function makeStale(
  destination = loginPathToResume(resumePath()),
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
  assertCurrent();
  const generation = response.headers.get(SESSION_GENERATION_HEADER);
  if (snapshot.status === "bound" && generation !== null && generation !== snapshot.generation) {
    makeStale();
  }
  if (response.ok) {
    if (generation === null) {
      throw new EneoApiError("The API response did not identify its browser session.", {
        status: 502
      });
    }
    return;
  }
  if (response.status !== 401 && response.status !== 403) return;
  let body: unknown;
  try {
    body = await response.clone().json();
  } catch {
    body = undefined;
  }
  const error = apiErrorFromResponse(response, body);
  assertCurrent();
  if (error.code === SESSION_MISMATCH) makeStale(undefined, error);
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
};

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
      pendingProbe = undefined;
    })
    .catch(() => {});
  return work;
}

async function probeSession(): Promise<void> {
  assertCurrent();
  const before = snapshot;
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
    assertCurrent();
    let generation: string | null;
    let logoutGeneration: string | undefined;
    if (response.status === 204) {
      generation = response.headers.get(SESSION_GENERATION_HEADER);
      if (!generation)
        throw new EneoApiError("The session probe returned no generation.", { status: 502 });
    } else if (response.status === 401) {
      if ((await errorCodeFromResponse(response)) === SESSION_MISMATCH) makeStale();
      generation = null;
      // An expired cookie still needs a binding for logout. It never grants
      // authenticated reads or lets this document adopt a later session.
      logoutGeneration = response.headers.get(SESSION_GENERATION_HEADER) ?? undefined;
    } else {
      const restriction =
        before.status === "unbound" && response.status === 403
          ? restrictionOf(await errorCodeFromResponse(response))
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
      await handleRefusal(response, SESSION_PROBE);
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        body = undefined;
      }
      throw apiErrorFromResponse(response, body);
    }
    assertCurrent();
    if (
      before.status === "bound" &&
      (before.generation !== generation || before.logoutGeneration !== logoutGeneration)
    )
      makeStale();
    publish({ status: "bound", generation, ...(logoutGeneration ? { logoutGeneration } : {}) });
  } catch (error) {
    if (snapshot.status === "bound") publish({ ...snapshot, checkError: error });
    throw error;
  }
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
  window.addEventListener("visibilitychange", visible, true);
  window.addEventListener("pageshow", restored, true);
  return () => {
    window.removeEventListener("visibilitychange", visible, true);
    window.removeEventListener("pageshow", restored, true);
  };
}
