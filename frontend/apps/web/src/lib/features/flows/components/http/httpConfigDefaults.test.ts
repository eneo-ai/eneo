import { describe, expect, it } from "vitest";

import {
  isSecretSentinel,
  parseHttpAuthoredConfig,
  type HttpAuthoredConfig
} from "./httpConfigTypes";
import { createDefaultHttpConfig, getAuthoredHttpUrlError } from "./httpConfigDefaults";
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

describe("getAuthoredHttpUrlError", () => {
  it("reports missing URL", () => {
    expect(getAuthoredHttpUrlError("")).toBe("HTTP_MISSING_URL");
  });

  it("reports invalid URL (not http/https)", () => {
    expect(getAuthoredHttpUrlError("ftp://example.com")).toBe("HTTP_INVALID_URL");
  });

  it("keeps literal non-http schemes invalid when the URL contains templates", () => {
    expect(getAuthoredHttpUrlError("ftp://{{host}}/upload")).toBe("HTTP_INVALID_URL");
  });

  it("reports a URL that carries credentials in its userinfo", () => {
    expect(getAuthoredHttpUrlError("https://user:pass@example.com/api")).toBe("HTTP_INVALID_URL");
  });

  it("reports userinfo even when the host is a template", () => {
    expect(getAuthoredHttpUrlError("https://alice:secret@{{host}}/api")).toBe("HTTP_INVALID_URL");
  });

  it("does not treat an at sign in the path as userinfo", () => {
    expect(getAuthoredHttpUrlError("https://example.com/users/a@b")).toBeNull();
  });

  it("reports unparseable URL", () => {
    expect(getAuthoredHttpUrlError("not-a-url")).toBe("HTTP_INVALID_URL");
  });

  it("accepts a valid https URL", () => {
    expect(getAuthoredHttpUrlError("https://api.example.com/v1")).toBeNull();
  });

  it("accepts templated authored URLs that the backend validates after interpolation", () => {
    expect(getAuthoredHttpUrlError("{{base_url}}/hook")).toBeNull();
    expect(getAuthoredHttpUrlError("https://{{host}}/hook")).toBeNull();
  });

  it("accepts uppercase HTTP schemes", () => {
    expect(getAuthoredHttpUrlError("HTTPS://api.example.com/hook")).toBeNull();
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
