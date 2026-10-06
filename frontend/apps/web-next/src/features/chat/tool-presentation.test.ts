import { describe, expect, it } from "vitest";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { Schema } from "@/lib/api/models";
import { humanizeToolName, isSkillCall, skillName, toolPresentation } from "./tool-presentation";

const t = (key: string, values?: Record<string, string>) =>
  `${key}${values?.query ? `:${values.query}` : ""}`;

describe("chat tool presentation", () => {
  it("labels a capability by purpose even when an external provider names the tool differently", () => {
    const call = {
      toolName: "look_up",
      input: { q: "weather" },
      providerMetadata: { eneo: { server_name: "Search Inc", purpose: "web_search" } }
    };
    expect(toolPresentation(call, t, false)).toMatchObject({
      label: "tool_web_search_query:weather",
      provider: "Search Inc"
    });
    expect(toolPresentation(call, t, true).label).toBe("tool_web_search_query_done:weather");
  });

  it("distinguishes image edits from new image generation", () => {
    const call = {
      toolName: "draw",
      input: { reference_images: ["ref"] },
      providerMetadata: { eneo: { server_name: "Image Inc", purpose: "image_generation" } }
    };
    expect(toolPresentation(call, t, false).label).toBe("tool_edit_image");
    expect(toolPresentation(call, t, true).label).toBe("tool_edit_image_done");
  });

  it("names untitled external tools from their identifier", () => {
    expect(humanizeToolName("search_knowledge_base")).toBe("Search knowledge base");
    expect(humanizeToolName("jira/create-issue")).toBe("Jira create issue");
    expect(humanizeToolName("__")).toBe("__");
    expect(toolPresentation({ toolName: "lou_troskelvarden" }, t, true).label).toBe(
      "Lou troskelvarden"
    );
  });

  it("localizes Eneo's knowledge tools and keeps external tool titles", () => {
    const internal = {
      toolName: "describe_source",
      providerMetadata: { eneo: { server_name: "knowledge" } }
    };
    expect(toolPresentation(internal, t, true).label).toBe("tool_describe_source_done");
    expect(
      toolPresentation(
        {
          toolName: "describe_source",
          providerMetadata: { eneo: { server_name: "Other", title: "Inspect source" } }
        },
        t,
        true
      ).label
    ).toBe("Inspect source");
  });

  it("recognizes Skill activations by server and preserves the display name", () => {
    const skill = {
      toolName: "planning",
      providerMetadata: { eneo: { server_name: "skills", title: "Planning Skill" } }
    };
    expect(isSkillCall(skill)).toBe(true);
    expect(skillName(skill)).toBe("Planning Skill");
    expect(toolPresentation(skill, t, false).label).toBe("tool_activate_skill");
    expect(
      isSkillCall({ toolName: "planning", providerMetadata: { eneo: { server_name: "Other" } } })
    ).toBe(false);
  });
});

/**
 * The backend reports whether a call ran on one of Eneo's own servers. An
 * admin can name an external server "files", "knowledge" or "skills", so a
 * call the backend marks external keeps its own name and title everywhere.
 * Rows without the flag fall back to the name.
 */
describe("an external server named like a built-in one", () => {
  const external = (serverName: string, toolName: string, title: string | null = null) => ({
    toolName,
    input: {
      url: "https://eneo.example/api/v1/files/0b0e4c5e-6f0a-4a57-9a3c-1f2a3b4c5d6e/original/download/"
    },
    providerMetadata: { eneo: { server_name: serverName, title, is_internal: false } }
  });

  it("keeps its own server name and tool title", () => {
    expect(toolPresentation(external("files", "read_file", "Read a file"), t, false)).toEqual({
      label: "Read a file",
      server: "files",
      provider: null
    });
    expect(toolPresentation(external("knowledge", "search_knowledge"), t, true)).toEqual({
      label: "Search knowledge",
      server: "knowledge",
      provider: null
    });
  });

  it("is not a Skill activation when named skills", () => {
    const skills = external("skills", "planning", "Planning Skill");
    expect(isSkillCall(skills)).toBe(false);
    expect(toolPresentation(skills, t, false)).toEqual({
      label: "Planning Skill",
      server: "skills",
      provider: null
    });
    expect(
      isSkillCall({
        toolName: "planning",
        providerMetadata: { eneo: { server_name: "skills", is_internal: true } }
      })
    ).toBe(true);
  });

  it("shows its name as the provider of a capability call", () => {
    const call = {
      toolName: "draw",
      providerMetadata: {
        eneo: { server_name: "image_generation", purpose: "image_generation", is_internal: false }
      }
    };
    expect(toolPresentation(call, t, false)).toMatchObject({
      label: "tool_generate_image",
      provider: "image_generation"
    });
    expect(
      toolPresentation(
        {
          ...call,
          providerMetadata: { eneo: { ...call.providerMetadata.eneo, is_internal: true } }
        },
        t,
        false
      ).provider
    ).toBeNull();
  });
});

describe("Eneo's own servers", () => {
  it("keep their localized labels when the backend marks the call internal", () => {
    const call = {
      toolName: "read_file",
      providerMetadata: {
        eneo: { server_name: "files", title: "Read attached file", is_internal: true }
      }
    };
    expect(toolPresentation(call, t, true)).toEqual({
      label: "tool_read_file_done",
      server: "internal_files_server"
    });
  });

  it("fall back to the server name on rows without the flag", () => {
    for (const is_internal of [undefined, null]) {
      const call = {
        toolName: "search_knowledge",
        providerMetadata: { eneo: { server_name: "knowledge", is_internal } }
      };
      expect(toolPresentation(call, t, false).server).toBe("knowledge");
      expect(toolPresentation(call, t, false).label).toBe("tool_search_knowledge");
    }
  });

  it("carry the flag from persisted history into the tool metadata", () => {
    const [, answer] = mapSessionMessages([
      {
        id: "m1",
        question: "Q",
        answer: "A",
        references: [],
        files: [],
        generated_files: [],
        tools: { assistants: [] },
        tool_calls: [
          { server_name: "files", tool_name: "read_file", tool_call_id: "c1", is_internal: false },
          { server_name: "files", tool_name: "read_file", tool_call_id: "c2" }
        ]
      } as Schema<"Message">
    ]);
    const tools = answer!.parts.filter((part) => part.type === "dynamic-tool");
    expect(toolPresentation(tools[0]!, t, true).server).toBe("files");
    expect(toolPresentation(tools[1]!, t, true).server).toBe("internal_files_server");
  });
});

describe("eneo tool metadata", () => {
  it("reads live (AI SDK v6) and saved-session metadata alike", async () => {
    const { eneoToolMetadata } = await import("./tool-presentation");
    const eneo = { server_name: "skills", title: "Upphandling" };
    expect(eneoToolMetadata({ toolName: "x", providerMetadata: { eneo } })).toEqual(eneo);
    expect(eneoToolMetadata({ toolName: "x", callProviderMetadata: { eneo } })).toEqual(eneo);
    expect(eneoToolMetadata({ toolName: "x", resultProviderMetadata: { eneo } })).toEqual(eneo);
    expect(isSkillCall({ toolName: "x", callProviderMetadata: { eneo } })).toBe(true);
    expect(eneoToolMetadata({ toolName: "x" })).toEqual({});
  });
});
