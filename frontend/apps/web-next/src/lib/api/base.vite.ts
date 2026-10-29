import { EventSource } from "eventsource";
import type { ApiEventSource } from "./base";
import { getSessionSignal, handleRefusal, prepareBrowserRequest } from "./refusal";

export const API_BASE = "";
export const CHAT_API = "/api/v1/conversations/?version=3";
export const JOB_EVENTS_PATH = "/api/v1/jobs/events/";

export const onBrowserApiRequest = ({ request }: { request: Request }): Promise<Request> =>
  prepareBrowserRequest(request);

export const onBrowserApiResponse = ({
  request,
  response
}: {
  request: Request;
  response: Response;
}): Promise<void> => handleRefusal(response, request.url);

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
