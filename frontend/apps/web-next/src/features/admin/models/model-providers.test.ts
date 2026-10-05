import { describe, expect, it } from "vitest";
import { comparableEndpoint, looksLikeMaskedApiKey } from "./model-providers";

describe("comparableEndpoint", () => {
  it("treats case, a default port and trailing slashes as the same destination", () => {
    const base = comparableEndpoint("https://api.example.com/v1");
    expect(comparableEndpoint("HTTPS://API.example.com/v1/")).toBe(base);
    expect(comparableEndpoint("https://api.example.com:443/v1//")).toBe(base);
    expect(comparableEndpoint("  https://api.example.com/v1  ")).toBe(base);
  });

  it("treats a new scheme, host, port, path or query as another destination", () => {
    const base = comparableEndpoint("https://api.example.com/v1");
    expect(comparableEndpoint("http://api.example.com/v1")).not.toBe(base);
    expect(comparableEndpoint("https://api.example.org/v1")).not.toBe(base);
    expect(comparableEndpoint("https://api.example.com:8443/v1")).not.toBe(base);
    expect(comparableEndpoint("https://api.example.com/v2")).not.toBe(base);
    expect(comparableEndpoint("https://api.example.com/v1?tenant=a")).not.toBe(base);
  });

  it("preserves case-sensitive paths and query values", () => {
    expect(comparableEndpoint("https://EXAMPLE.COM/Service?tenant=A")).not.toBe(
      comparableEndpoint("https://example.com/service?tenant=a")
    );
  });

  it("assumes https for a bare host and keeps a non-URL comparable", () => {
    expect(comparableEndpoint("api.example.com/v1/")).toBe(
      comparableEndpoint("https://api.example.com/v1")
    );
    expect(comparableEndpoint("not a url/")).toBe("not a url");
    expect(comparableEndpoint("   ")).toBe("");
  });
});

describe("looksLikeMaskedApiKey", () => {
  it("recognises the dialog's masked display forms", () => {
    expect(looksLikeMaskedApiKey("...4f2a")).toBe(true);
    expect(looksLikeMaskedApiKey(" ••••••• ")).toBe(true);
    expect(looksLikeMaskedApiKey("****")).toBe(true);
  });

  it("accepts a real key and says nothing about an empty value", () => {
    expect(looksLikeMaskedApiKey("sk-live-4f2a")).toBe(false);
    expect(looksLikeMaskedApiKey("")).toBe(false);
  });
});
