import { describe, expect, it } from "vitest";

import { APPLY_API_ERROR_CODES, parseAIBuilderApplyError } from "./flowAIBuilderApplyError";

describe("parseAIBuilderApplyError", () => {
  it("parses generated-client response errors from IntricError.response", () => {
    const parsed = parseAIBuilderApplyError({
      status: 400,
      response: {
        code: "flow_is_published",
        message: "Flow is published",
        context: { flow_id: "flow-1", published_version: 3 }
      }
    });

    expect(parsed).toEqual({
      code: "flow_is_published",
      message: "Flow is published",
      context: { flow_id: "flow-1", published_version: 3 }
    });
  });

  it("keeps stale revision behavior for older body-shaped test errors", () => {
    const parsed = parseAIBuilderApplyError({
      body: {
        code: "stale_revision",
        message: "Flow was modified",
        context: { latest_revision: 9 }
      }
    });

    expect(parsed).toEqual({
      code: "stale_revision",
      message: "Flow was modified",
      context: { latest_revision: 9 }
    });
  });

  it("falls back from HTTP 409 to stale_revision when the backend body is missing", () => {
    const parsed = parseAIBuilderApplyError({
      status: 409,
      message: "Conflict"
    });

    expect(parsed).toEqual({
      code: "stale_revision",
      message: "Conflict",
      context: {}
    });
  });

  it("turns connection failures into a typed network error", () => {
    const parsed = parseAIBuilderApplyError({
      status: 0,
      stage: "CONNECTION",
      message: "Failed to fetch"
    });

    expect(parsed).toEqual({
      code: "network",
      message: "Failed to fetch",
      context: { status: 0, stage: "CONNECTION" }
    });
  });

  it("returns unknown instead of null for unrecognized backend codes", () => {
    const parsed = parseAIBuilderApplyError({
      status: 400,
      response: {
        code: "unexpected_backend_code",
        message: "Unexpected failure",
        context: { retryable: false }
      }
    });

    expect(parsed).toEqual({
      code: "unknown",
      message: "Unexpected failure",
      context: {
        retryable: false,
        status: 400,
        original_code: "unexpected_backend_code"
      }
    });
  });

  it("round-trips every typed backend apply error code", () => {
    for (const code of Object.keys(APPLY_API_ERROR_CODES)) {
      const parsed = parseAIBuilderApplyError({
        status: 400,
        response: {
          code,
          message: `Message for ${code}`,
          context: { code }
        }
      });

      expect(parsed).toEqual({
        code,
        message: `Message for ${code}`,
        context: { code }
      });
    }
  });
});
