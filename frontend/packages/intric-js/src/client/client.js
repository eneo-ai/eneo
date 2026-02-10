/**
 * @typedef {Object} Client
 * @property {import('../types/fetch').IntricFetchFunction} fetch Typed fetch function for the Intric backend.
 * @property {import('../types/fetch').IntricStreamFunction} stream Fetch function specifically for streaming answers from an assistant.
 * @property {import('../types/fetch').IntricXhrFunction} xhr
 * @property {URL} baseUrl Base url this client uses
 * @property {string} version Version of the Api this client was created for
 */

import { readEvents } from "./stream";
import { xhr } from "./xhr";

/**
 * Creates a client to request intric resources over a typesafe interface.
 * Requires either an api key or a user token to authenticate requests.
 * @param {Object} args
 * @param  {string} args.baseUrl Base URL of the Intric backend
 * @param  {string} [args.apiKey] Intric API key
 * @param  {string} [args.token] Intric auth token obtained through logging in
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
        IntricError.throw(error, { endpoint: `${httpMethod}@${url}`, payload });
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
        IntricError.throw(error, { endpoint: `STREAM@${url}`, payload });
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
        IntricError.throw(error, { endpoint: `${httpMethod}@${url}`, payload });
      }
    },

    version,
    baseUrl: new URL(baseUrl)
  };
}

/**
 * Expand parameters and endpoint into a full url
 * @param baseUrl {string} Base Url of the intric instance
 * @param endpoint {string} An endpoint with {param} placeholdes
 * @param params {{query?: Record<string, string>, path?: Record<string, string>} | undefined} A dictionary of {params} to replace with their respective values
 * @returns {string} Returns the fully expanded url
 */
function parseUrl(baseUrl, endpoint, params) {
  const url = new URL(baseUrl);

  if (params?.path) {
    Object.entries(params.path).forEach(([param, value]) => {
      endpoint = endpoint.replace(`{${param}}`, value);
    });
  }

  url.pathname = endpoint;

  if (params?.query) {
    Object.entries(params.query).forEach(([param, value]) => {
      if (value !== undefined) {
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
        intric_error_code: 0
      },
      response.headers
    );
  }

  if (response.ok) {
    return parsed;
  }

  throw new PartialError("RESPONSE", response.status, parsed, response.headers);
}

/** An intermediate error that is throw during running a request on the client. Needs to be finalised into an IntricError */
export class PartialError extends Error {
  /**
   * Construct a new ServerError
   * @param {"CONNECTION" | "SERVER" | "RESPONSE"} stage On what stage the error was thrown, during connection, on the server on while processing the response
   * @param {number} status
   * @param {{[x: string]: any } & {message?: string, intric_error_code: import("../types/resources").IntricErrorCode}} [parsedResponse] Parsed json response from server
   * @param {Headers} [headers] Response headers
   */
  constructor(stage, status, parsedResponse, headers) {
    const detail = typeof parsedResponse?.detail === "string" ? parsedResponse.detail : undefined;
    const message =
      status === 500
        ? "Upstream server error"
        : (parsedResponse?.message ?? detail ?? "See details for more info.");
    super(message);
    /** @type {any | undefined} Server response parsed as JSON object (if possible). */
    this.detail = parsedResponse;
    this.status = status;
    this.stage = stage;

    // Extract error code from X-Error-Code header (for audit sessions) or response body
    const headerCode = headers?.get("x-error-code");
    this.code = headerCode || parsedResponse?.intric_error_code || 0;

    /** @type {Headers | undefined} */
    this.headers = headers;
  }
}

/** An error thrown by the intric.js client */
export class IntricError extends Error {
  /**
   * Construct a new IntricError
   * @param {string} message Error message
   * @param {"CONNECTION" | "SERVER" | "RESPONSE" | "UNKNOWN"} stage On what stage the error was thrown, during connection, on the server on while processing the response
   * @param {number} status HTTP status
   * @param {import("../types/resources").IntricErrorCode | 0} code The backend will return an error code in most cases that can give additional info
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
    /** @type {import("../types/resources").IntricErrorCode | 0} The backend will return an error code in most cases */
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
    let message;
    if (this.status === 422) {
      const reason = this.response.detail[0]?.ctx?.reason;
      const msg = this.response.detail[0]?.msg ?? "A validation error occured.";
      message = reason ?? msg;
    } else {
      message = this.message;
    }
    return message;
  }

  /**
   * Rethrow an error as an IntricError
   * @param {unknown} error
   * @param {{endpoint: string; payload?: object;}} requestInfo
   */
  static throw(error, requestInfo) {
    if (error instanceof PartialError) {
      throw new IntricError(
        error.message,
        error.stage,
        error.status,
        error.code,
        error.detail,
        requestInfo,
        error.headers
      );
    }
    if (error instanceof Error) {
      throw new IntricError(error.message, "CONNECTION", 0, 0, "No response text", requestInfo);
    }
    throw new IntricError("UNKNOWN ERROR", "UNKNOWN", 0, 0, "No response text", requestInfo);
  }
}
