import { describe, expect, it } from "vitest";

import type { HttpAuthoredConfig, HttpAuth } from "./httpConfigTypes";
import { getHttpSummaryText, getAuthLabel, getAuthLabelEn } from "./httpConfigHelpers";

function makeConfig(overrides: Partial<HttpAuthoredConfig> = {}): HttpAuthoredConfig {
  return {
    url: "https://api.example.com/v1/data",
    auth: { mode: "none" },
    timeout_seconds: 30,
    body: { mode: "none" },
    custom_headers: [],
    response_format: null,
    ...overrides,
  };
}

describe("getHttpSummaryText", () => {
  it("returns empty string for null config", () => {
    expect(getHttpSummaryText(null, "POST")).toBe("");
  });

  it("returns empty string for undefined config", () => {
    expect(getHttpSummaryText(undefined, "GET")).toBe("");
  });

  it("returns empty string for config with empty URL", () => {
    expect(getHttpSummaryText(makeConfig({ url: "" }), "POST")).toBe("");
  });

  it("includes method, hostname, auth, and timeout for a basic config", () => {
    const text = getHttpSummaryText(makeConfig(), "GET");

    expect(text).toContain("GET");
    expect(text).toContain("api.example.com");
    expect(text).toContain("Ingen");
    expect(text).toContain("30s");
  });

  it("includes body label for auto mode", () => {
    const text = getHttpSummaryText(makeConfig({ body: { mode: "auto" } }), "POST");

    expect(text).toContain("JSON");
  });

  it("includes body label for text_template mode", () => {
    const text = getHttpSummaryText(
      makeConfig({ body: { mode: "text_template", template: "hello" } }),
      "POST",
    );

    expect(text).toContain("Text");
  });

  it("omits body label for none mode", () => {
    const text = getHttpSummaryText(makeConfig({ body: { mode: "none" } }), "GET");
    const parts = text.split(" \u2022 ");

    expect(parts).not.toContain("JSON");
    expect(parts).not.toContain("Text");
  });

  it("falls back to truncated URL when parsing fails", () => {
    const text = getHttpSummaryText(makeConfig({ url: "not-a-valid-url" }), "POST");

    expect(text).toContain("not-a-valid-url");
  });

  it("uses bullet separator between parts", () => {
    const text = getHttpSummaryText(makeConfig(), "POST");

    expect(text).toContain(" \u2022 ");
  });

  it("shows bearer auth label", () => {
    const text = getHttpSummaryText(
      makeConfig({ auth: { mode: "bearer_token", token: "tok" } as any }),
      "POST",
    );

    expect(text).toContain("Bearer");
  });
});

describe("getAuthLabel", () => {
  it("returns Bearer for bearer_token", () => {
    expect(getAuthLabel({ mode: "bearer_token", token: "x" } as HttpAuth)).toBe("Bearer");
  });

  it("returns API-nyckel for api_key", () => {
    expect(getAuthLabel({ mode: "api_key", header_name: "X-Key", key: "x" } as HttpAuth)).toBe("API-nyckel");
  });

  it("returns Basic for basic_auth", () => {
    expect(getAuthLabel({ mode: "basic_auth", username: "u", password: "p" } as HttpAuth)).toBe("Basic");
  });

  it("returns Ingen for none", () => {
    expect(getAuthLabel({ mode: "none" })).toBe("Ingen");
  });
});

describe("getAuthLabelEn", () => {
  it("returns Bearer token for bearer_token", () => {
    expect(getAuthLabelEn({ mode: "bearer_token", token: "x" } as HttpAuth)).toBe("Bearer token");
  });

  it("returns API key for api_key", () => {
    expect(getAuthLabelEn({ mode: "api_key", header_name: "X-Key", key: "x" } as HttpAuth)).toBe("API key");
  });

  it("returns Basic auth for basic_auth", () => {
    expect(getAuthLabelEn({ mode: "basic_auth", username: "u", password: "p" } as HttpAuth)).toBe("Basic auth");
  });

  it("returns None for none", () => {
    expect(getAuthLabelEn({ mode: "none" })).toBe("None");
  });
});
