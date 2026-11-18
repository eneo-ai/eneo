import { EventSource } from "eventsource";
export type ApiEventSource = {
  readonly readyState: number;
  addEventListener(type: string, listener: (event: Event) => void): void;
  close(): void;
};

import { getSessionSignal, handleRefusal, prepareBrowserRequest } from "./refusal";

export const API_BASE = "";
export const CHAT_API = "/api/v1/conversations/?version=3";
export const JOB_EVENTS_PATH = "/api/v1/jobs/events/";

// Login discovery is public, so it has no authenticated session generation.
function isPublicDiscovery(request: Request): boolean {
  const path = new URL(request.url).pathname;
  return (
    request.method === "GET" &&
    (path === "/api/v1/auth/federation-status" || path === "/api/v1/auth/tenants")
  );
}

export const onBrowserApiRequest = async ({ request }: { request: Request }): Promise<Request> =>
  isPublicDiscovery(request)
    ? new Request(request, { credentials: "omit" })
    : prepareBrowserRequest(request);

export const onBrowserApiResponse = async ({
  request,
  response
}: {
  request: Request;
  response: Response;
}): Promise<void> => {
  if (!isPublicDiscovery(request)) await handleRefusal(response, request.url);
};

export const onRawRefusal = handleRefusal;

/** Raw fetch and typed middleware share the same request/response contract. */
export const apiFetch: typeof fetch = async (input, init) => {
  const request = await prepareBrowserRequest(
    new Request(
      input instanceof Request ? input : new URL(String(input), window.location.href),
      init
    )
  );
  const response = await fetch(request);
  await handleRefusal(response, request.url);
  return response;
};

/** Native EventSource cannot send headers; reuse the protocol implementation. */
export function createApiEventSource(url: string): ApiEventSource {
  const source = new EventSource(new URL(url, window.location.href), { fetch: apiFetch });
  const signal = getSessionSignal();
  const close = () => {
    signal.removeEventListener("abort", close);
    source.close();
  };
  if (signal.aborted) close();
  else signal.addEventListener("abort", close, { once: true });
  return {
    get readyState() {
      return source.readyState;
    },
    addEventListener: (type, listener) => source.addEventListener(type, listener),
    close
  };
}
