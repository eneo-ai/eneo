import { apiErrorFromResponse, EneoApiError, errorCodeFromResponse } from "./errors";
import { getQueryClient } from "./query";
import { loginPathToResume } from "@/lib/auth/module-login";
import { passwordChangeUrl } from "@/lib/auth/password-change-path";
import { safeNextPath } from "@/lib/auth/safe-next";
import { navigateTo } from "@/lib/navigate-to";

export const SESSION_GENERATION_HEADER = "Eneo-Session-Generation";
const SESSION_PROBE = "/api/v1/auth/session/";
const SESSION_MISMATCH = 9080;

export type SessionSnapshot =
  | { status: "unbound" }
  | { status: "bound"; generation: string | null; checkError?: unknown }
  | { status: "stale"; destination: string };

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

function makeStale(destination = loginPathToResume(resumePath()), error = staleError()): never {
  if (snapshot.status !== "stale") {
    // Publish before navigation: beforeunload may cancel the document load.
    publish({ status: "stale", destination });
    requests.abort(new DOMException("The browser session changed", "AbortError"));
    const queryClient = getQueryClient();
    void queryClient.cancelQueries();
    queryClient.clear();
    if (!publicAuthPage()) navigateTo(destination);
  }
  throw error;
}

/** The explicit retry keeps the document blocked until a new document loads. */
export function reloadSession(): void {
  if (snapshot.status === "stale") navigateTo(snapshot.destination);
}

/** Check headers before a response body reaches a cache or stream consumer. */
export const handleRefusal: (response: Response, requestUrl: string) => Promise<void> = async (
  response
) => {
  if (typeof window === "undefined") return;
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
  if (response.status === 403 && error.code === 9025) makeStale("/deactivated", error);
  if (response.status === 403 && error.code === 9070)
    makeStale(passwordChangeUrl(resumePath()), error);
  if (publicAuthPage()) return;
  if (response.status === 401) {
    const auditCode = response.headers.get("X-Error-Code");
    if (auditCode === "AUDIT_SESSION_REQUIRED" || auditCode === "AUDIT_SESSION_EXPIRED") return;
    makeStale(undefined, error);
  }
};

/** Every cookie transport uses this before sending, including XHR uploads. */
export async function prepareBrowserRequest(request: Request): Promise<Request> {
  if (pendingProbe) await pendingProbe;
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
  const headers = new Headers(request.headers);
  headers.set(SESSION_GENERATION_HEADER, snapshot.generation);
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
    if (snapshot.status !== "stale") throw error;
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
  if (before.status === "bound" && before.generation !== null) {
    headers.set(SESSION_GENERATION_HEADER, before.generation);
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
    if (response.status === 204) {
      generation = response.headers.get(SESSION_GENERATION_HEADER);
      if (!generation)
        throw new EneoApiError("The session probe returned no generation.", { status: 502 });
    } else if (response.status === 401) {
      if ((await errorCodeFromResponse(response)) === SESSION_MISMATCH) makeStale();
      generation = null;
    } else {
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
    if (before.status === "bound" && before.generation !== generation) makeStale();
    publish({ status: "bound", generation });
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
