import { describe, expect, it } from "vitest";

import {
  isSecretSentinel,
  parseHttpAuthoredConfig,
  type HttpAuthoredConfig
} from "./httpConfigTypes";
import {
  createDefaultHttpConfig,
  validateHttpConfig,
  isHttpConfigured,
  getAuthoredHttpUrlError
} from "./httpConfigDefaults";
import { parseHttpTestVariables } from "./httpTestVariables";

function makeConfig(overrides: Partial<HttpAuthoredConfig> = {}): HttpAuthoredConfig {
  return {
    url: "https://example.com/api",
    auth: { mode: "none" },
    timeout_seconds: 30,
    body: { mode: "none" },
    custom_headers: [],
    response_format: null,
    ...overrides
  };
}

describe("createDefaultHttpConfig", () => {
  it("creates output defaults with auto body mode", () => {
    const config = createDefaultHttpConfig("output", "POST");

    expect(config.url).toBe("");
    expect(config.auth).toEqual({ mode: "none" });
    expect(config.timeout_seconds).toBe(30);
    expect(config.body.mode).toBe("auto");
    expect(config.custom_headers).toEqual([]);
    expect(config.response_format).toBeNull();
  });

  it("creates input defaults with none body mode and text response format", () => {
    const config = createDefaultHttpConfig("input", "GET");

    expect(config.body.mode).toBe("none");
    expect(config.response_format).toBe("text");
  });
});

describe("parseHttpAuthoredConfig", () => {
  it("preserves valid authored config fields", () => {
    const defaults = createDefaultHttpConfig("output", "POST");
    const config = parseHttpAuthoredConfig(
      {
        url: "https://api.example.com/hook",
        auth: { mode: "bearer_token", token: { $secret: "stored" } },
        timeout_seconds: 45,
        body: { mode: "text_template", template: "hello" },
        custom_headers: [{ name: "X-Trace", value: "abc", secret: false }],
        response_format: "json"
      },
      defaults
    );

    expect(config).toEqual({
      url: "https://api.example.com/hook",
      auth: { mode: "bearer_token", token: { $secret: "stored" } },
      timeout_seconds: 45,
      body: { mode: "text_template", template: "hello" },
      custom_headers: [{ name: "X-Trace", value: "abc", secret: false }],
      response_format: "json"
    });
  });

  it("recovers missing fields from caller defaults", () => {
    const defaults = makeConfig({
      url: "https://default.example.com",
      auth: { mode: "api_key", header_name: "X-Default", key: { $secret: "stored" } },
      timeout_seconds: 42,
      body: { mode: "text_template", template: "fallback" },
      custom_headers: [{ name: "X-Default", value: "value", secret: false }],
      response_format: "text"
    });

    expect(parseHttpAuthoredConfig({}, defaults)).toEqual(defaults);
  });

  it("recovers malformed scalar and discriminant fields from caller defaults", () => {
    const defaults = makeConfig({
      url: "https://default.example.com",
      auth: { mode: "basic_auth", username: "default-user", password: "default-pass" },
      timeout_seconds: 42,
      body: { mode: "text_template", template: "fallback" },
      custom_headers: [{ name: "X-Default", value: "value", secret: false }],
      response_format: "text"
    });

    const config = parseHttpAuthoredConfig(
      {
        url: 7,
        auth: { mode: "oauth", token: "ignored" },
        timeout_seconds: "fast",
        body: { mode: "xml", template: 5 },
        custom_headers: "not-an-array",
        response_format: "xml"
      },
      defaults
    );

    expect(config).toEqual(defaults);
  });

  it("recovers malformed custom header entries without dropping valid entries", () => {
    const defaults = createDefaultHttpConfig("output", "POST");
    const config = parseHttpAuthoredConfig(
      {
        custom_headers: [
          { name: 5, value: 7, secret: "yes" },
          null,
          { name: "X-Secret", value: { $secret: "stored" }, secret: true }
        ]
      },
      defaults
    );

    expect(config.custom_headers).toEqual([
      { name: "", value: "", secret: false },
      { name: "X-Secret", value: { $secret: "stored" }, secret: true }
    ]);
  });

  it("identifies only the stored secret sentinel shape", () => {
    expect(isSecretSentinel({ $secret: "stored" })).toBe(true);
    expect(isSecretSentinel(null)).toBe(false);
    expect(isSecretSentinel("stored")).toBe(false);
    expect(isSecretSentinel([])).toBe(false);
    expect(isSecretSentinel({})).toBe(false);
    expect(isSecretSentinel({ $secret: "wrong" })).toBe(false);
  });
});

describe("validateHttpConfig", () => {
  it("reports missing URL", () => {
    const errors = validateHttpConfig(makeConfig({ url: "" }), "output", "POST");

    expect(errors).toEqual([expect.objectContaining({ field: "url", code: "HTTP_MISSING_URL" })]);
  });

  it("reports invalid URL (not http/https)", () => {
    const errors = validateHttpConfig(makeConfig({ url: "ftp://example.com" }), "output", "POST");

    expect(errors).toEqual([expect.objectContaining({ field: "url", code: "HTTP_INVALID_URL" })]);
  });

  it("keeps literal non-http schemes invalid when the URL contains templates", () => {
    const errors = validateHttpConfig(
      makeConfig({ url: "ftp://{{host}}/upload" }),
      "output",
      "POST"
    );

    expect(errors).toEqual([expect.objectContaining({ field: "url", code: "HTTP_INVALID_URL" })]);
  });

  it("reports unparseable URL", () => {
    const errors = validateHttpConfig(makeConfig({ url: "not-a-url" }), "output", "POST");

    expect(errors).toEqual([expect.objectContaining({ field: "url", code: "HTTP_INVALID_URL" })]);
  });

  it("accepts a valid https URL", () => {
    const errors = validateHttpConfig(
      makeConfig({ url: "https://api.example.com/v1" }),
      "output",
      "POST"
    );

    expect(errors).toEqual([]);
  });

  it("accepts templated authored URLs that the backend validates after interpolation", () => {
    expect(validateHttpConfig(makeConfig({ url: "{{base_url}}/hook" }), "output", "POST")).toEqual(
      []
    );
    expect(
      validateHttpConfig(makeConfig({ url: "https://{{host}}/hook" }), "output", "POST")
    ).toEqual([]);
  });

  it("accepts uppercase HTTP schemes", () => {
    expect(getAuthoredHttpUrlError("HTTPS://api.example.com/hook")).toBeNull();
  });

  it("reports missing bearer token", () => {
    const errors = validateHttpConfig(
      makeConfig({ auth: { mode: "bearer_token", token: "" } }),
      "output",
      "POST"
    );

    expect(errors).toContainEqual(
      expect.objectContaining({ field: "auth", code: "HTTP_MISSING_AUTH" })
    );
  });

  it("skips auth error when bearer token is a secret sentinel", () => {
    const errors = validateHttpConfig(
      makeConfig({ auth: { mode: "bearer_token", token: { $secret: "stored" } } }),
      "output",
      "POST"
    );

    expect(errors.find((e) => e.field === "auth")).toBeUndefined();
  });

  it("reports missing api_key", () => {
    const errors = validateHttpConfig(
      makeConfig({ auth: { mode: "api_key", header_name: "X-Key", key: "" } }),
      "output",
      "POST"
    );

    expect(errors).toContainEqual(
      expect.objectContaining({ field: "auth", code: "HTTP_MISSING_AUTH" })
    );
  });

  it("reports missing basic_auth credentials", () => {
    const errors = validateHttpConfig(
      makeConfig({ auth: { mode: "basic_auth", username: "", password: "" } }),
      "output",
      "POST"
    );

    expect(errors).toContainEqual(
      expect.objectContaining({ field: "auth", code: "HTTP_MISSING_AUTH" })
    );
  });

  it("reports body not allowed for GET with json_template", () => {
    const errors = validateHttpConfig(
      makeConfig({ body: { mode: "json_template", template: "{}" } }),
      "input",
      "GET"
    );

    expect(errors).toContainEqual(
      expect.objectContaining({ field: "body", code: "HTTP_BODY_NOT_ALLOWED_FOR_GET" })
    );
  });

  it("allows GET with body mode none", () => {
    const errors = validateHttpConfig(makeConfig({ body: { mode: "none" } }), "input", "GET");

    expect(errors.find((e) => e.field === "body")).toBeUndefined();
  });

  it("reports invalid JSON in json_template body", () => {
    const errors = validateHttpConfig(
      makeConfig({ body: { mode: "json_template", template: "not json" } }),
      "output",
      "POST"
    );

    expect(errors).toContainEqual(
      expect.objectContaining({ field: "body", code: "HTTP_INVALID_BODY_JSON" })
    );
  });

  it("allows json_template with template expressions", () => {
    const errors = validateHttpConfig(
      makeConfig({ body: { mode: "json_template", template: '{"data": "{{step_output}}"}' } }),
      "output",
      "POST"
    );

    expect(errors.find((e) => e.code === "HTTP_INVALID_BODY_JSON")).toBeUndefined();
  });

  it("reports timeout below range", () => {
    const errors = validateHttpConfig(makeConfig({ timeout_seconds: 0 }), "output", "POST");

    expect(errors).toContainEqual(
      expect.objectContaining({ field: "timeout", code: "HTTP_TIMEOUT_OUT_OF_RANGE" })
    );
  });

  it("reports timeout above range", () => {
    const errors = validateHttpConfig(makeConfig({ timeout_seconds: 121 }), "output", "POST");

    expect(errors).toContainEqual(
      expect.objectContaining({ field: "timeout", code: "HTTP_TIMEOUT_OUT_OF_RANGE" })
    );
  });

  it("accepts timeout at boundaries", () => {
    expect(validateHttpConfig(makeConfig({ timeout_seconds: 1 }), "output", "POST")).toEqual([]);
    expect(validateHttpConfig(makeConfig({ timeout_seconds: 120 }), "output", "POST")).toEqual([]);
  });
});

describe("isHttpConfigured", () => {
  it("returns false for null", () => {
    expect(isHttpConfigured(null)).toBe(false);
  });

  it("returns false for undefined", () => {
    expect(isHttpConfigured(undefined)).toBe(false);
  });

  it("returns false for config with empty URL", () => {
    expect(isHttpConfigured(makeConfig({ url: "" }))).toBe(false);
  });

  it("returns false for config with whitespace-only URL", () => {
    expect(isHttpConfigured(makeConfig({ url: "   " }))).toBe(false);
  });

  it("returns true for config with a URL", () => {
    expect(isHttpConfigured(makeConfig({ url: "https://example.com" }))).toBe(true);
  });
});

describe("parseHttpTestVariables", () => {
  it("treats an empty variables editor as an empty context", () => {
    expect(parseHttpTestVariables("  \n ")).toEqual({ ok: true, value: {} });
  });

  it("parses JSON objects", () => {
    expect(parseHttpTestVariables('{"base_url":"https://api.example.com","case":7}')).toEqual({
      ok: true,
      value: { base_url: "https://api.example.com", case: 7 }
    });
  });

  it("rejects malformed JSON", () => {
    expect(parseHttpTestVariables("{bad")).toEqual({ ok: false });
  });

  it("rejects non-object JSON values", () => {
    expect(parseHttpTestVariables("[1,2]")).toEqual({ ok: false });
    expect(parseHttpTestVariables("null")).toEqual({ ok: false });
    expect(parseHttpTestVariables('"value"')).toEqual({ ok: false });
  });
});
