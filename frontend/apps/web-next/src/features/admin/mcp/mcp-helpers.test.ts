import { describe, expect, it } from "vitest";
import { hostFromUrl, initials, readableParams, toolRisk } from "./mcp-helpers";

describe("hostFromUrl", () => {
  it("extracts the host from a valid url", () => {
    expect(hostFromUrl("https://api.github.com/mcp")).toBe("api.github.com");
    expect(hostFromUrl("https://mcp.diariet.internal:8443/")).toBe("mcp.diariet.internal:8443");
  });

  it("falls back for malformed but host-bearing strings and returns null otherwise", () => {
    expect(hostFromUrl("http://example.com")).toBe("example.com");
    expect(hostFromUrl("not a url")).toBeNull();
    expect(hostFromUrl(null)).toBeNull();
    expect(hostFromUrl("")).toBeNull();
  });
});

describe("initials", () => {
  it("derives up to two uppercase initials", () => {
    expect(initials("Diariesök")).toBe("DI");
    expect(initials("Kommunens dokument MCP")).toBe("KM");
    expect(initials("  ")).toBe("?");
  });
});

describe("toolRisk", () => {
  it("flags state-changing verbs as write", () => {
    for (const name of [
      "create_issue",
      "updateRecord",
      "delete-file",
      "sendMessage",
      "post_comment"
    ]) {
      expect(toolRisk({ name })).toBe("write");
    }
  });

  it("treats read-style verbs as read", () => {
    for (const name of ["get_weather", "list_files", "searchDocuments", "read_page", "fetch_url"]) {
      expect(toolRisk({ name })).toBe("read");
    }
  });
});

describe("readableParams", () => {
  it("flattens properties with type, required flag, and description", () => {
    const schema = {
      type: "object",
      required: ["city"],
      properties: {
        city: { type: "string", description: "The city to look up" },
        days: { type: "integer" },
        tags: { type: "array", items: { type: "string" } }
      }
    };
    expect(readableParams(schema)).toEqual([
      { name: "city", type: "string", required: true, description: "The city to look up" },
      { name: "days", type: "integer", required: false, description: null },
      { name: "tags", type: "string[]", required: false, description: null }
    ]);
  });

  it("returns an empty list for absent or malformed schemas", () => {
    expect(readableParams(null)).toEqual([]);
    expect(readableParams(undefined)).toEqual([]);
    expect(readableParams({ type: "object" })).toEqual([]);
  });
});
