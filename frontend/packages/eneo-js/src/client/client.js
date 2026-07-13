/**
 * @typedef {Object} Client
 * @property {import('../types/fetch').EneoFetchFunction} fetch Typed fetch function for the Eneo backend.
 * @property {import('../types/fetch').EneoBinaryFetchFunction} binaryFetch Typed fetch function for authenticated binary downloads.
 * @property {import('../types/fetch').EneoStreamFunction} stream Fetch function specifically for streaming answers from an assistant.
 * @property {import('../types/fetch').EneoXhrFunction} xhr
 * @property {URL} baseUrl Base url this client uses
 * @property {string} version Version of the Api this client was created for
 */

import { readEvents } from "./stream.js";
import { xhr } from "./xhr.js";

/** @typedef {string | number | boolean | null | undefined} QueryParameterValue */

/**
 * @param {unknown} value
 * @returns {value is { message: string }}
 */
function hasReadableErrorMessage(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    "message" in value &&
    typeof value.message === "string" &&
    value.message.length > 0
  );
}

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
  const version = "DEV-20260713T141031Z"; // # Client version auto-updates when running the updater, do not edit this line.
  const baseUrl = args.baseUrl;
  const _fetch = args.fetch ?? fetch;

  /** @type {{"X-API-Key": string} | {Authorization: string} | {}} */
  const auth =
    args.apiKey !== undefined
      ? { "X-API-Key": args.apiKey }
      : args.token !== undefined
        ? { Authorization: `Bearer ${args.token}` }
        : {};

  return {
    fetch: async (endpoint, { method, params, requestBody, signal, headers }) => {
      const payload = parsePayload(requestBody);
      const httpMethod = String(method).toUpperCase();
      let requestEndpoint = `${httpMethod}@${baseUrl}${endpoint}`;

      try {
        const url = parseUrl(baseUrl, endpoint, params);
        requestEndpoint = `${httpMethod}@${url}`;
        const response = await _fetch(url, {
          method: httpMethod,
          headers: {
            ...auth,
            ...payload.header,
            ...parseHeaderParams(params),
            ...headers
          },
          body: payload.body,
          signal,
          credentials: "include" // Required for cookies (audit sessions, etc.)
        });
        /** @type {any} The generated fetch type owns the response shape; runtime validation belongs at the API boundary. */
        const parsed = await parseResponse(response);
        return parsed;
      } catch (error) {
        EneoError.throw(error, { endpoint: requestEndpoint, payload });
        throw error;
      }
    },

    binaryFetch: async (endpoint, { method, params, requestBody, signal, headers }) => {
      const payload = parsePayload(requestBody);
      const httpMethod = String(method).toUpperCase();
      let requestEndpoint = `${httpMethod}@${baseUrl}${endpoint}`;

      try {
        const url = parseUrl(baseUrl, endpoint, params);
        requestEndpoint = `${httpMethod}@${url}`;
        const response = await _fetch(url, {
          method: httpMethod,
          headers: {
            ...auth,
            ...payload.header,
            ...parseHeaderParams(params),
            ...headers
          },
          body: payload.body,
          signal,
          credentials: "include"
        });
        return await parseBinaryResponse(response);
      } catch (error) {
        EneoError.throw(error, { endpoint: requestEndpoint, payload });
        throw error;
      }
    },

    stream: async (endpoint, { params, requestBody }, callbacks, abortController) => {
      const payload = parsePayload(requestBody);
      let requestEndpoint = `STREAM@${baseUrl}${endpoint}`;
      const headers = { ...auth, ...payload.header, accept: "text/event-stream" };
      const body = payload.body;

      const controller = abortController ?? new AbortController();
      /** @type {(ev: {id: string; event: string; data: string;}) => void} */
      const onMessage = (ev) => {
        callbacks.onMessage?.(ev, controller);
      };

      try {
        const url = parseUrl(baseUrl, endpoint, params);
        requestEndpoint = `STREAM@${url}`;
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
        EneoError.throw(error, { endpoint: requestEndpoint, payload });
      }
    },

    xhr: async (endpoint, { method, params, requestBody }, callbacks, abortController) => {
      const payload = parsePayload(requestBody);
      const httpMethod = String(method).toUpperCase();
      let requestEndpoint = `${httpMethod}@${baseUrl}${endpoint}`;

      try {
        const url = parseUrl(baseUrl, endpoint, params);
        requestEndpoint = `${httpMethod}@${url}`;
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
        /** @type {any} The generated fetch type owns the response shape; runtime validation belongs at the API boundary. */
        const parsed = await parseResponse(response);
        return parsed;
      } catch (error) {
        EneoError.throw(error, { endpoint: requestEndpoint, payload });
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
 * @param params {{query?: Record<string, QueryParameterValue | readonly QueryParameterValue[]>, path?: Record<string, string>} | undefined} A dictionary of {params} to replace with their respective values
 * @returns {string} Returns the fully expanded url
 */
function parseUrl(baseUrl, endpoint, params) {
  const url = new URL(baseUrl);

  if (params?.path) {
    Object.entries(params.path).forEach(([param, value]) => {
      if (value === undefined || value === null || value === "" || value === "undefined") {
        throw new Error(`Cannot build API request: path parameter "${param}" is missing.`);
      }
      endpoint = endpoint.replace(`{${param}}`, String(value));
    });
  }

  url.pathname = endpoint;

  if (params?.query) {
    Object.entries(params.query).forEach(([param, value]) => {
      const values = Array.isArray(value) ? value : [value];
      values.forEach((queryValue) => {
        if (queryValue !== undefined) {
          url.searchParams.append(param, String(queryValue));
        }
      });
    });
  }

  return url.toString();
}

/**
 * @param {{header?: Record<string, string | number | boolean | null | undefined>} | undefined} params
 * @returns {Record<string, string> | undefined}
 */
function parseHeaderParams(params = undefined) {
  if (!params?.header) {
    return undefined;
  }

  return Object.entries(params.header).reduce((headers, [name, value]) => {
    if (value !== undefined && value !== null) {
      headers[name] = String(value);
    }
    return headers;
  }, /** @type {Record<string, string>} */ ({}));
}

/**
 * Parse a request body into a payload.
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
 * Parse the response body.
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
      parsed = JSON.parse(text);
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
 * Parse a successful binary response without losing the authenticated error
 * handling path used by JSON endpoints.
 * @param response {Response} `Response` from fetch
 * @returns {Promise<import('../types/fetch').EneoBinaryResponse>}
 * @throws {PartialError}
 */
async function parseBinaryResponse(response) {
  if (!response.ok) {
    await parseResponse(response);
  }

  const contentDisposition = response.headers.get("Content-Disposition") ?? undefined;
  return {
    blob: await response.blob(),
    contentType: response.headers.get("Content-Type") ?? "application/octet-stream",
    filename: getContentDispositionFilename(contentDisposition),
    headers: response.headers
  };
}

/**
 * @param {string | undefined} contentDisposition
 * @returns {string | undefined}
 */
function getContentDispositionFilename(contentDisposition) {
  if (!contentDisposition) {
    return undefined;
  }
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(contentDisposition);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1].replaceAll("+", "%20"));
  }
  const asciiMatch = /filename="?([^";]+)"?/i.exec(contentDisposition);
  return asciiMatch?.[1];
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

    // Extract error code from X-Error-Code header (for audit sessions) or response body
    const headerCode = headers?.get("x-error-code");
    this.code = headerCode || parsedResponse?.eneo_error_code || 0;

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
    if (this.status !== 422) {
      return this.message;
    }

    const response = this.response;
    const generalErrorMessage = Array.isArray(response?.details?.errors)
      ? response.details.errors.find(hasReadableErrorMessage)?.message
      : undefined;
    if (generalErrorMessage) {
      return generalErrorMessage;
    }

    if (typeof response?.message === "string" && response.message.length > 0) {
      return response.message;
    }

    const legacyError = Array.isArray(response?.detail) ? response.detail[0] : undefined;
    const legacyReason = legacyError?.ctx?.reason;
    if (typeof legacyReason === "string" && legacyReason.length > 0) {
      return legacyReason;
    }

    const legacyMessage = legacyError?.msg;
    if (typeof legacyMessage === "string" && legacyMessage.length > 0) {
      return legacyMessage;
    }

    return this.message || "A validation error occurred.";
  }

  /** @returns {string | undefined} */
  getTraceId() {
    return this.headers?.get("X-Trace-Id") ?? this.headers?.get("X-Correlation-ID") ?? undefined;
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
