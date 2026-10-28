import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import {
  apiErrorFromResponse,
  EneoApiError,
  errorReference,
  errorReferenceLines,
  extractTraceId,
  getErrorMessage,
  unwrap
} from "./errors";

function errorResponse(status: number, headers: Record<string, string> = {}) {
  return new Response(null, { status, headers });
}

describe("apiErrorFromResponse", () => {
  it("parses the GeneralError shape (message + eneo_error_code + details)", () => {
    const error = apiErrorFromResponse(errorResponse(403, { "x-trace-id": "abc123" }), {
      message: "Quota exceeded",
      eneo_error_code: 9008,
      code: "quota_exceeded",
      details: { quota: 100 }
    });

    expect(error).toBeInstanceOf(EneoApiError);
    expect(error.status).toBe(403);
    expect(error.code).toBe(9008);
    expect(error.reason).toBe("quota_exceeded");
    expect(error.message).toBe("Quota exceeded");
    expect(error.traceId).toBe("abc123");
    expect(error.details).toEqual({ quota: 100 });
  });

  it("keeps the backend error id on unexpected failures", () => {
    const error = apiErrorFromResponse(errorResponse(500, { "x-trace-id": "trace-123" }), {
      error: "Internal server error",
      error_id: "8bc91e0a",
      message: "An unexpected error occurred."
    });

    expect(error.errorId).toBe("8bc91e0a");
    expect(error.traceId).toBe("trace-123");
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
      error: { message: "Not found", eneo_error_code: 9000 },
      response: errorResponse(404, { "x-trace-id": "abc" })
    });

    const error = await unwrap(result).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(EneoApiError);
    expect((error as EneoApiError).status).toBe(404);
    expect((error as EneoApiError).code).toBe(9000);
    expect((error as EneoApiError).traceId).toBe("abc");
  });
});

/** The app's real catalog, looked up by any key as the error mapping does. */
const translator = (locale: string, messages: Record<string, string>) =>
  createTranslator({ locale, messages });

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

  it("names an integration refusal in the viewer's language, keeping Microsoft's code", () => {
    const refusal = (reason: string, message: string, status = 400) =>
      getErrorMessage(
        apiErrorFromResponse(errorResponse(status), {
          message,
          eneo_error_code: 9007,
          code: reason
        }),
        translator("en", en)
      );

    expect(refusal("sharepoint_credentials_invalid", "SharePoint credentials are invalid")).toBe(
      "Microsoft refused the organization's SharePoint sign-in. An administrator must sign in again or update the app's secret."
    );
    expect(refusal("oauth_code_rejected", "Microsoft did not accept the code (AADSTS70008).")).toBe(
      "Microsoft did not accept the sign-in. Start the sign-in again. (AADSTS70008)"
    );
    expect(refusal("oauth_client_rejected", "Refused (AADSTS7000215).")).toBe(
      "Microsoft did not accept the app's credentials. An administrator must check the app's client ID and client secret. (AADSTS7000215)"
    );
    expect(refusal("integration_knowledge_syncing", "Syncing", 409)).toBe(
      "The source is syncing. Try again when the sync has finished."
    );
    // Another reason keeps the usual mapping.
    expect(refusal("something_else", "Something else")).toBe(
      getErrorMessage(
        new EneoApiError("Something else", { status: 400, code: 9007 }),
        translator("en", en)
      )
    );
  });

  it("falls back to the generic message for non-API errors", () => {
    expect(getErrorMessage(new Error("boom"), t)).toBe("t(request_failed)");
    expect(getErrorMessage(undefined, t)).toBe("t(request_failed)");
  });

  it("says what blocks deleting a prompt the governance uses, not a taken name", () => {
    const error = new EneoApiError("Prompt 'Standard' is referenced by the governance policy.", {
      status: 409,
      code: 9069
    });

    expect(getErrorMessage(error, translator("sv", sv))).toBe(
      "Prompten är aktiv i styrningen för personlig assistent. Avaktivera den där först, och ta sedan bort den."
    );
  });

  it("localizes the password refusals, as the SvelteKit app does", () => {
    const refused = (code: number) =>
      getErrorMessage(new EneoApiError("Refused", { status: 400, code }), translator("sv", sv));

    expect(refused(9058)).toBe(
      "Det nya lösenordet måste skilja sig från det nuvarande lösenordet."
    );
    expect(refused(9059)).toBe("Det nya lösenordet uppfyller inte lösenordspolicyn.");
    expect(refused(9060)).toBe("Lösenordsbyte är inte tillgängligt för det här kontot.");
    expect(refused(9061)).toBe("Det nuvarande lösenordet är felaktigt.");
  });

  it("words an unexpected failure in the user's language instead of the backend's English", () => {
    // The 500 body: `{ error, error_id, message }` with no eneo_error_code.
    const error = apiErrorFromResponse(errorResponse(500), {
      error: "Internal server error",
      error_id: "8bc91e0a",
      message:
        "An unexpected error occurred. Please try again or contact support with the error_id."
    });

    expect(getErrorMessage(error, translator("sv", sv))).toBe(
      "Vi upplever vissa svårigheter, försök igen senare."
    );
  });

  it("words a taken name for every resource that answers with it, not only models", () => {
    // Providers, MCP servers, templates, files, modules and models all send 9017.
    const error = new EneoApiError("An MCP server with this name already exists.", {
      status: 409,
      code: 9017
    });

    expect(getErrorMessage(error, translator("sv", sv))).toBe(
      "Namnet används redan. Välj ett annat namn."
    );
    expect(getErrorMessage(error, translator("en", en))).toBe(
      "This name is already in use. Choose a different one."
    );
  });
});

describe("errorReference", () => {
  const failure = (ids: { errorId?: string; traceId?: string }) =>
    new EneoApiError("Failed", { status: 500, ...ids });

  it("returns both the backend error id and the trace id", () => {
    expect(errorReference(failure({ errorId: "8bc91e0a", traceId: "trace-1" }))).toEqual({
      errorId: "8bc91e0a",
      traceId: "trace-1"
    });
  });

  it("returns whichever id the error carries", () => {
    expect(errorReference(failure({ errorId: "8bc91e0a" }))).toEqual({ errorId: "8bc91e0a" });
    expect(errorReference(failure({ traceId: "trace-1" }))).toEqual({ traceId: "trace-1" });
  });

  it("returns no ids for an error without them or a non-API error", () => {
    expect(errorReference(failure({}))).toEqual({});
    expect(errorReference(new Error("boom"))).toEqual({});
    expect(errorReference(null)).toEqual({});
  });

  it("labels the ids in the user's language", () => {
    expect(
      errorReferenceLines(
        failure({ errorId: "8bc91e0a", traceId: "trace-1" }),
        translator("sv", sv)
      )
    ).toEqual(["Fel-ID: 8bc91e0a", "Spårnings-ID: trace-1"]);
    expect(errorReferenceLines(new Error("boom"), translator("sv", sv))).toEqual([]);
  });
});
