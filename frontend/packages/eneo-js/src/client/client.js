/**
 * @typedef {Object} Client
 * @property {import('../types/fetch').EneoFetchFunction} fetch Typed fetch function for the Eneo backend.
 * @property {import('../types/fetch').EneoStreamFunction} stream Fetch function specifically for streaming answers from an assistant.
 * @property {import('../types/fetch').EneoXhrFunction} xhr
 * @property {URL} baseUrl Base url this client uses
 * @property {string} version Version of the Api this client was created for
 */

import { readEvents } from "./stream.js";
import { xhr } from "./xhr.js";

/**
 * Creates a client to request eneo resources over a typesafe interface.
 * Requires either an api key or a user token to authenticate requests.
 * @param {Object} args
 * @param  {string} args.baseUrl Base URL of the Eneo backend
 * @param  {string} [args.apiKey] Eneo API key
 * @param  {string} [args.token] Eneo auth token obtained through logging in
 * @param {(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>} [args.fetch] Alternative fetch function to use, defaults to native fetch
 * @returns {Client}
 */

export function createClient(args) {
  const version = "DEV"; // # Client version auto-updates when running the updater, do not edit this line.
  const baseUrl = args.baseUrl;
  const _fetch = args.fetch ?? fetch;

  /** @type {{"api-key": string} | {Authorization: string} | {}} */
  const auth =
    args.apiKey !== undefined
      ? { "api-key": args.apiKey }
      : args.token !== undefined
        ? { Authorization: `Bearer ${args.token}` }
        : {};

  return {
    fetch: async (endpoint, { method, params, requestBody }) => {
      const url = parseUrl(baseUrl, endpoint, params);
      const payload = parsePayload(requestBody);
      const httpMethod = String(method).toUpperCase();

      try {
        const response = await _fetch(url, {
          method: httpMethod,
          headers: {
            ...auth,
            ...payload.header
          },
          body: payload.body,
          credentials: "include" // Required for cookies (audit sessions, etc.)
        });
        /** @type {any} We need to cast this through any – we just got to hope for the correctness of the schema... */
        const parsed = await parseResponse(response);
        return parsed;
      } catch (error) {
        EneoError.throw(error, { endpoint: `${httpMethod}@${url}`, payload });
      }
    },

    stream: async (endpoint, { params, requestBody }, callbacks, abortController) => {
      const url = parseUrl(baseUrl, endpoint, params);
      const payload = parsePayload(requestBody);
      const headers = { ...auth, ...payload.header, accept: "text/event-stream" };
      const body = payload.body;

      const controller = abortController ?? new AbortController();
      /** @type {(ev: {id: string; event: string; data: string;}) => void} */
      const onMessage = (ev) => {
        callbacks.onMessage?.(ev, controller);
      };

      try {
        const response = await _fetch(url, {
          body,
          headers,
          method: "POST",
          signal: controller.signal,
          credentials: "include" // Required for cookies
        });

        await readEvents(response, {
          onOpen: callbacks.onOpen,
          onClose: callbacks.onClose,
          onMessage
        });
      } catch (error) {
        EneoError.throw(error, { endpoint: `STREAM@${url}`, payload });
      }
    },

    xhr: async (endpoint, { method, params, requestBody }, callbacks, abortController) => {
      const url = parseUrl(baseUrl, endpoint, params);
      const payload = parsePayload(requestBody);
      const httpMethod = String(method).toUpperCase();

      try {
        const response = await xhr(
          url,
          {
            method: httpMethod,
            headers: {
              ...auth,
              ...payload.header
            },
            body: payload.body
          },
          callbacks,
          abortController
        );
        /** @type {any} We need to cast this through any – we just got to hope for the correctness of the schema... */
        const parsed = await parseResponse(response);
        return parsed;
      } catch (error) {
        EneoError.throw(error, { endpoint: `${httpMethod}@${url}`, payload });
      }
    },

    version,
    baseUrl: new URL(baseUrl)
  };
}

/**
 * Expand parameters and endpoint into a full url
 * @param baseUrl {string} Base Url of the eneo instance
 * @param endpoint {string} An endpoint with {param} placeholdes
 * @param params {{query?: Record<string, string>, path?: Record<string, string>} | undefined} A dictionary of {params} to replace with their respective values
 * @returns {string} Returns the fully expanded url
 */
function parseUrl(baseUrl, endpoint, params) {
  const url = new URL(baseUrl);

  if (params?.path) {
    Object.entries(params.path).forEach(([param, value]) => {
      if (value === undefined || value === null || value === "undefined" || value === "null") {
        throw new Error(
          `Missing path parameter "${param}" for endpoint "${endpoint}" (got ${value === undefined ? "undefined" : JSON.stringify(value)}).`
        );
      }
      endpoint = endpoint.replace(`{${param}}`, value);
    });
  }

  url.pathname = endpoint;

  if (params?.query) {
    Object.entries(params.query).forEach(([param, value]) => {
      if (value !== undefined && value !== null) {
        url.searchParams.append(param, value);
      }
    });
  }

  return url.toString();
}

/**
 * Parse a requestbody into a payload
 * @param requestBody {Record<string, any> | undefined} Object of Content-Type and payload, e.g. {"application/json": {...}}
 * @returns Returns appropriate header and serialized payload
 */
function parsePayload(requestBody = undefined) {
  if (requestBody === undefined) {
    return { header: undefined, body: undefined };
  }

  // We only support one type of payload
  const [contentType, payload] = Object.entries(requestBody)[0];

  // Multipart sets its own header, so bail here:
  if (contentType === "multipart/form-data") {
    return { header: undefined, body: payload };
  }

  /** @type {Record<string, (value: any) => string>} */
  const serializers = {
    "application/json": JSON.stringify
  };

  const serialize = Object.hasOwn(serializers, contentType)
    ? serializers[contentType]
    : (/** We assume this is already serialised @type {string} */ body) => body;
  return { header: { "Content-Type": contentType }, body: serialize(payload) };
}

/**
 * Parse the Resposes body
 *  - will return parsed json if body is present
 *  - will return undefined if body is empty
 * Throws error if body is returned but cannot be parsed or reponse is not ok
 * @param response {Response} `Response` from fetch
 * @returns {Promise<object | undefined>}
 * @throws {PartialError}
 */
async function parseResponse(response) {
  let parsed;
  let text;
  try {
    text = await response.text(); // Parse it as text
    if (text !== "") {
      parsed = JSON.parse(text); //
    }
  } catch (err) {
    throw new PartialError(
      "RESPONSE",
      response.status,
      {
        message: `Could not parse server response (1).\n${text ? text : "No body received"}`,
        eneo_error_code: 0
      },
      response.headers
    );
  }

  if (response.ok) {
    return parsed;
  }

  throw new PartialError("RESPONSE", response.status, parsed, response.headers);
}

/**
 * Response headers this client reads off responses, lowercased.
 *
 * SvelteKit refuses header reads on responses fetched inside a load function
 * unless the header is permitted by the `filterSerializedResponseHeaders`
 * option — see `headerFilterHandle` in the web app's `hooks.server.ts`, which
 * allows exactly this list. Add a header here when the client starts reading
 * it, or SSR loses the value.
 *
 * @type {readonly string[]}
 */
export const ENEO_RESPONSE_HEADERS = ["x-trace-id", "x-correlation-id", "x-error-code"];

/**
 * Read a response header, yielding `undefined` instead of throwing.
 *
 * Every header this client reads is diagnostic metadata attached to an error
 * that is already being reported. A throw here would replace that error with a
 * confusing one about header access — which is exactly what SvelteKit's load
 * fetch does for headers missing from `filterSerializedResponseHeaders`.
 *
 * @param {Headers | undefined} headers
 * @param {string} name Lowercased header name
 * @returns {string | undefined}
 */
function readResponseHeader(headers, name) {
  try {
    return headers?.get(name) ?? undefined;
  } catch {
    return undefined;
  }
}

/**
 * Read the backend trace id off a response.
 *
 * Prefers ``X-Trace-Id`` (set by TraceIdResponseMiddleware on every response,
 * including 4xx/5xx) and falls back to the legacy ``X-Correlation-ID`` during
 * the migration period when both headers are emitted in parallel.
 *
 * @param {Headers | undefined} headers Response headers
 * @returns {string | undefined} 32-char hex trace id, or undefined if no span
 *   was active when the response was produced.
 */
export function readTraceId(headers) {
  return (
    readResponseHeader(headers, "x-trace-id") ?? readResponseHeader(headers, "x-correlation-id")
  );
}

/** An intermediate error that is throw during running a request on the client. Needs to be finalised into an EneoError */
export class PartialError extends Error {
  /**
   * Construct a new ServerError
   * @param {"CONNECTION" | "SERVER" | "RESPONSE"} stage On what stage the error was thrown, during connection, on the server on while processing the response
   * @param {number} status
   * @param {{[x: string]: any } & {message?: string, eneo_error_code: import("../types/resources").EneoErrorCode}} [parsedResponse] Parsed json response from server
   * @param {Headers} [headers] Response headers
   */
  constructor(stage, status, parsedResponse, headers) {
    // Structured 4xx responses use `detail: {code, message}` (see
    // require_user_for_creation / require_user_identity in the backend).
    // Validation errors use `detail: [...]`. Fall back to string detail for
    // older shapes.
    const detailRaw = parsedResponse?.detail;
    const detailObjectMessage =
      detailRaw && typeof detailRaw === "object" && !Array.isArray(detailRaw)
        ? detailRaw.message
        : undefined;
    const detailString = typeof detailRaw === "string" ? detailRaw : undefined;
    const message =
      status === 500
        ? "Upstream server error"
        : (parsedResponse?.message ??
          detailObjectMessage ??
          detailString ??
          "See details for more info.");
    super(message);
    /** @type {any | undefined} Server response parsed as JSON object (if possible). */
    this.detail = parsedResponse;
    this.status = status;
    this.stage = stage;

    // `code` is compared against the numeric ErrorCodes enum, so only the body
    // may set it. The audit endpoints send a symbolic X-Error-Code
    // (AUDIT_SESSION_REQUIRED) which would never match one of those codes;
    // read it off `headers` if a call site ever needs it.
    this.code = parsedResponse?.eneo_error_code || 0;

    /** @type {Headers | undefined} */
    this.headers = headers;
  }
}

/** An error thrown by the eneo.js client */
export class EneoError extends Error {
  /**
   * Construct a new EneoError
   * @param {string} message Error message
   * @param {"CONNECTION" | "SERVER" | "RESPONSE" | "UNKNOWN"} stage On what stage the error was thrown, during connection, on the server on while processing the response
   * @param {number} status HTTP status
   * @param {import("../types/resources").EneoErrorCode | 0} code The backend will return an error code in most cases that can give additional info
   * @param {Object} [response] Parsed json response from server
   * @param {{endpoint: string; payload?: object;}} request
   * @param {Headers} [headers] Response headers
   */
  constructor(message, stage, status, code, response, request = { endpoint: "" }, headers) {
    super(message);
    /** @type {"CONNECTION" | "SERVER" | "RESPONSE" | "UNKNOWN"} During what stage the error happened. */
    this.stage = stage;
    /** @type {number} If this was a server error, this is the status code returned by the server. */
    this.status = status;
    /** @type {import("../types/resources").EneoErrorCode | 0} The backend will return an error code in most cases */
    this.code = code;
    /** @type {any | undefined} Server response parsed as JSON object. */
    this.response = response;
    /** @type {{endpoint: string; payload?: object;}} Info about the request during which the error occured. */
    this.request = request;
    /** @type {Headers | undefined} */
    this.headers = headers;
  }

  /**
   * Get a message that can be presented to users, ie. in an alert
   */
  getReadableMessage() {
    if (this.status === 422) {
      // A 422 does not guarantee FastAPI's `detail` array: an unparseable body
      // or a gateway-generated response leaves it missing, and reading through
      // it would throw inside whatever is already reporting this error.
      const first = Array.isArray(this.response?.detail) ? this.response.detail[0] : undefined;
      return first?.ctx?.reason ?? first?.msg ?? "A validation error occured.";
    }
    return this.message;
  }

  /**
   * Return the backend trace ID for this error, suitable for support reports.
   *
   * @returns {string | undefined} See {@link readTraceId}. Undefined as well
   *   when the header could not be read.
   */
  getTraceId() {
    return readTraceId(this.headers);
  }

  /**
   * Rethrow an error as an EneoError
   * @param {unknown} error
   * @param {{endpoint: string; payload?: object;}} requestInfo
   */
  static throw(error, requestInfo) {
    if (error instanceof PartialError) {
      throw new EneoError(
        error.message,
        error.stage,
        error.status,
        /** @type {import("../types/resources").EneoErrorCode | 0} */ (error.code),
        error.detail,
        requestInfo,
        error.headers
      );
    }
    if (error instanceof Error) {
      throw new EneoError(error.message, "CONNECTION", 0, 0, "No response text", requestInfo);
    }
    throw new EneoError("UNKNOWN ERROR", "UNKNOWN", 0, 0, "No response text", requestInfo);
  }
}
