import { describe, expect, it } from "vitest";
import {
  capabilityProviderDetail,
  internalToolDoneLabel,
  isBuiltinToolCall,
  serverDisplayName,
  toolDisplayName
} from "./internalToolLabels";

/**
 * A tool call renders as a built-in step when it serves a capability (web
 * search, image generation), whichever provider backs it, or when it runs on
 * one of Eneo's own loopback servers. General external servers keep their
 * cards. Rows persisted before `purpose` existed fall back to the name rule.
 */
describe("isBuiltinToolCall", () => {
  it("treats a capability call from an external provider as built in", () => {
    expect(isBuiltinToolCall({ server_name: "GDM Safe Search", purpose: "web_search" })).toBe(true);
  });

  it("keeps general external servers external", () => {
    expect(isBuiltinToolCall({ server_name: "GDM Safe Search", purpose: null })).toBe(false);
    expect(isBuiltinToolCall({ server_name: "Jira", purpose: "general" })).toBe(false);
  });

  it("keeps Eneo's own servers built in, with or without a purpose", () => {
    expect(isBuiltinToolCall({ server_name: "knowledge" })).toBe(true);
    expect(isBuiltinToolCall({ server_name: "image_generation" })).toBe(true);
    expect(
      isBuiltinToolCall({ server_name: "image_generation", purpose: "image_generation" })
    ).toBe(true);
  });
});

describe("labels", () => {
  it("labels a web search by purpose and folds the query in", () => {
    const args = { query: "lasagne recept" };
    const running = toolDisplayName("search", "GDM Safe Search", "Search", args, "web_search");
    const done = internalToolDoneLabel("search", "GDM Safe Search", args, "web_search");

    expect(running).toContain("lasagne recept");
    expect(running).not.toBe("Search");
    expect(done).toContain("lasagne recept");
    expect(done).not.toBe(running);
  });

  it("accepts q as the query argument", () => {
    expect(toolDisplayName("search", "Provider", null, { q: "bygglov" }, "web_search")).toContain(
      "bygglov"
    );
  });

  it("labels an external image provider like the built-in one", () => {
    const external = toolDisplayName(
      "make_picture",
      "Pixel Co",
      "Make picture",
      {},
      "image_generation"
    );
    const builtin = toolDisplayName("generate_image", "image_generation", null, {});

    expect(external).toBe(builtin);
  });

  it("falls back to the server title, then the raw name, for general tools", () => {
    expect(toolDisplayName("lookup", "Jira", "Look up issue", {}, null)).toBe("Look up issue");
    expect(toolDisplayName("lookup", "Jira", null, {}, null)).toBe("lookup");
    expect(internalToolDoneLabel("lookup", "Jira", {}, null)).toBeNull();
  });

  it("names the server line by capability for providers and by name otherwise", () => {
    expect(serverDisplayName("GDM Safe Search", "web_search")).not.toBe("GDM Safe Search");
    expect(serverDisplayName("Jira", null)).toBe("Jira");
    expect(serverDisplayName("knowledge")).not.toBe("knowledge");
  });

  it("shows the provider name as detail only for external capability calls", () => {
    expect(
      capabilityProviderDetail({ server_name: "GDM Safe Search", purpose: "web_search" })
    ).toBe("GDM Safe Search");
    expect(
      capabilityProviderDetail({ server_name: "image_generation", purpose: "image_generation" })
    ).toBeNull();
    expect(capabilityProviderDetail({ server_name: "Jira", purpose: null })).toBeNull();
  });
});
