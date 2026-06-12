import { describe, expect, it } from "vitest";
import {
  apiErrorFromResponse,
  EneoApiError,
  extractTraceId,
  getErrorMessage,
  unwrap
} from "./errors";

function errorResponse(status: number, headers: Record<string, string> = {}) {
  return new Response(null, { status, headers });
}

describe("apiErrorFromResponse", () => {
  it("parses the GeneralError shape (message + intric_error_code + details)", () => {
    const error = apiErrorFromResponse(errorResponse(403, { "x-trace-id": "abc123" }), {
      message: "Quota exceeded",
      intric_error_code: 9008,
      details: { quota: 100 }
    });

    expect(error).toBeInstanceOf(EneoApiError);
    expect(error.status).toBe(403);
    expect(error.code).toBe(9008);
    expect(error.message).toBe("Quota exceeded");
    expect(error.traceId).toBe("abc123");
    expect(error.details).toEqual({ quota: 100 });
  });

  it("parses a string detail", () => {
    const error = apiErrorFromResponse(errorResponse(404), { detail: "Space not found" });

    expect(error.message).toBe("Space not found");
    expect(error.code).toBeUndefined();
  });

  it("parses an object detail with message and code", () => {
    const error = apiErrorFromResponse(errorResponse(400), {
      detail: { message: "Bad input", code: 9007 }
    });

    expect(error.message).toBe("Bad input");
    expect(error.code).toBe(9007);
  });

  it("parses a FastAPI validation array detail", () => {
    const detail = [
      { loc: ["body", "name"], msg: "Field required", type: "missing" },
      { loc: ["body", "size"], msg: "Input should be a valid integer", type: "int_parsing" }
    ];
    const error = apiErrorFromResponse(errorResponse(422), { detail });

    expect(error.message).toBe("Field required; Input should be a valid integer");
    expect(error.details).toEqual(detail);
  });

  it("falls back to a status message for unrecognized bodies", () => {
    expect(apiErrorFromResponse(errorResponse(500), undefined).message).toBe(
      "Request failed with status 500"
    );
    expect(apiErrorFromResponse(errorResponse(502), "upstream died").message).toBe(
      "Request failed with status 502"
    );
  });
});

describe("extractTraceId", () => {
  it("prefers x-trace-id over the legacy x-correlation-id", () => {
    const headers = new Headers({ "x-trace-id": "trace", "x-correlation-id": "corr" });
    expect(extractTraceId(headers)).toBe("trace");
  });

  it("falls back to x-correlation-id", () => {
    expect(extractTraceId(new Headers({ "x-correlation-id": "corr" }))).toBe("corr");
  });

  it("returns undefined when neither header is present", () => {
    expect(extractTraceId(new Headers())).toBeUndefined();
  });
});

describe("unwrap", () => {
  it("returns data on success", async () => {
    const result = Promise.resolve({
      data: { items: [] },
      error: undefined,
      response: new Response("{}", { status: 200 })
    });

    await expect(unwrap(result)).resolves.toEqual({ items: [] });
  });

  it("throws an EneoApiError carrying the parsed body on failure", async () => {
    const result = Promise.resolve({
      data: undefined,
      error: { message: "Not found", intric_error_code: 9000 },
      response: errorResponse(404, { "x-trace-id": "abc" })
    });

    const error = await unwrap(result).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(EneoApiError);
    expect((error as EneoApiError).status).toBe(404);
    expect((error as EneoApiError).code).toBe(9000);
    expect((error as EneoApiError).traceId).toBe("abc");
  });
});

describe("getErrorMessage", () => {
  const t = (key: string) => `t(${key})`;

  it("maps known backend error codes to localized messages", () => {
    const error = new EneoApiError("Quota exceeded", { status: 403, code: 9008 });
    expect(getErrorMessage(error, t)).toBe("t(eneo_error_9008)");
  });

  it("falls back to the backend message for unmapped codes", () => {
    const error = new EneoApiError("Crawl already running", { status: 400, code: 9021 });
    expect(getErrorMessage(error, t)).toBe("Crawl already running");
  });

  it("falls back to the generic message for non-API errors", () => {
    expect(getErrorMessage(new Error("boom"), t)).toBe("t(request_failed)");
    expect(getErrorMessage(undefined, t)).toBe("t(request_failed)");
  });
});
