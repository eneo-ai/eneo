import { describe, expect, it } from "vitest";
import {
  capabilityProviderDetail,
  internalReadFileId,
  internalToolDoneLabel,
  isBuiltinToolCall,
  isInternalToolCall,
  isSkillActivation,
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

/**
 * The backend reports whether a call ran on one of Eneo's own servers. An
 * admin can name an external server "files", "knowledge" or "skills", so a
 * call the backend marks external keeps its own name and title everywhere,
 * including on the approval card. Rows without the flag fall back to the name.
 */
describe("an external server named like a built-in one", () => {
  const external = { server_name: "files", is_internal: false };

  it("is not a built-in tool call", () => {
    expect(isInternalToolCall(external)).toBe(false);
    expect(isBuiltinToolCall(external)).toBe(false);
    expect(isInternalToolCall({ server_name: "knowledge", is_internal: false })).toBe(false);
  });

  it("keeps its own server name and tool title", () => {
    expect(serverDisplayName("files", null, false)).toBe("files");
    expect(serverDisplayName("knowledge", null, false)).toBe("knowledge");
    expect(toolDisplayName("read_file", "files", "Read a file", {}, null, false)).toBe(
      "Read a file"
    );
    expect(internalToolDoneLabel("read_file", "files", {}, null, false)).toBeNull();
  });

  it("does not resolve an attachment name from its arguments", () => {
    const args = {
      url: "https://eneo.example/api/v1/files/0b0e4c5e-6f0a-4a57-9a3c-1f2a3b4c5d6e/original/download/"
    };
    expect(internalReadFileId("files", "read_file", args, false)).toBeNull();
    expect(internalReadFileId("files", "read_file", args, true)).toBe(
      "0b0e4c5e-6f0a-4a57-9a3c-1f2a3b4c5d6e"
    );
  });

  it("is not a Skill activation when named skills", () => {
    expect(isSkillActivation({ server_name: "skills", is_internal: false })).toBe(false);
    expect(serverDisplayName("skills", null, false)).toBe("skills");
    expect(isSkillActivation({ server_name: "skills", is_internal: true })).toBe(true);
  });

  it("shows its name as the detail of a capability call", () => {
    expect(
      capabilityProviderDetail({
        server_name: "image_generation",
        purpose: "image_generation",
        is_internal: false
      })
    ).toBe("image_generation");
  });
});

describe("Eneo's own servers", () => {
  it("keep their localized labels when the backend marks the call internal", () => {
    expect(isInternalToolCall({ server_name: "files", is_internal: true })).toBe(true);
    expect(serverDisplayName("files", null, true)).not.toBe("files");
    expect(toolDisplayName("read_file", "files", "Read attached file", {}, null, true)).not.toBe(
      "Read attached file"
    );
  });

  it("fall back to the server name on rows without the flag", () => {
    expect(isInternalToolCall({ server_name: "knowledge" })).toBe(true);
    expect(isInternalToolCall({ server_name: "knowledge", is_internal: null })).toBe(true);
    expect(serverDisplayName("knowledge")).not.toBe("knowledge");
  });
});
