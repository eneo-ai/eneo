/**
 * One retry for SSR fetches that die on the wire.
 *
 * The app layout fires several parallel backend fetches on every authenticated
 * page load. Server-side fetch pools keep-alive sockets, and any backend or
 * proxy that closes an idle socket while a request crosses it produces a
 * network-level failure ("fetch failed", ECONNRESET) — which used to reject
 * the whole load and render the 500 page instead of the workspace.
 *
 * A closed-socket race is safe to retry exactly when the request could not
 * have been processed twice: idempotent methods only, network-level errors
 * only. HTTP error responses are results, not failures, and are never retried.
 */

const IDEMPOTENT_METHODS = new Set(["GET", "HEAD"]);

/** Transport-level codes undici surfaces when a pooled socket dies. */
const TRANSIENT_CODES = new Set(["ECONNRESET", "EPIPE", "UND_ERR_SOCKET", "UND_ERR_INFO"]);

export function isTransientNetworkError(error: unknown): boolean {
  let current: unknown = error;
  // fetch wraps the transport error: TypeError("fetch failed") -> cause chain.
  for (let depth = 0; current && depth < 5; depth++) {
    if (current instanceof AggregateError) {
      return current.errors.some((inner) => isTransientNetworkError(inner));
    }
    if (typeof current === "object") {
      const code = (current as { code?: unknown }).code;
      if (typeof code === "string" && TRANSIENT_CODES.has(code)) {
        return true;
      }
      current = (current as { cause?: unknown }).cause;
    } else {
      break;
    }
  }
  return false;
}

export async function fetchWithTransientRetry(
  request: Request,
  fetchFn: typeof fetch
): Promise<Response> {
  if (!IDEMPOTENT_METHODS.has(request.method)) {
    return fetchFn(request);
  }
  // A Request is consumed by fetch even without a body; keep a copy to resend.
  const retryRequest = request.clone();
  try {
    return await fetchFn(request);
  } catch (error) {
    if (!isTransientNetworkError(error)) {
      throw error;
    }
    // The failed socket is gone from the pool; the retry gets a fresh one.
    return fetchFn(retryRequest);
  }
}
