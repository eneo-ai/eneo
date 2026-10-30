import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { Schema } from "@/lib/api/models";
import en from "@/lib/i18n/messages/en.json";
import sv from "@/lib/i18n/messages/sv.json";
import {
  humanizeToolName,
  isSkillCall,
  skillName,
  toolPresentation,
  toolTarget
} from "./tool-presentation";

const t = (key: string, values?: Record<string, string | number>) =>
  `${key}${values?.query ? `:${values.query}` : ""}${values?.offset ? `:${values.offset}` : ""}`;

describe("chat tool presentation", () => {
  it("labels a question to the person as Eneo's own step, not by the server's name", () => {
    const call = {
      toolName: "ask_user",
      input: { question: "Vem ska läsa PM:et?" },
      providerMetadata: { eneo: { server_name: "questions", is_internal: true } }
    };
    expect(toolPresentation(call, t, false)).toEqual({
      label: "tool_ask_user",
      server: "questions_server"
    });
    expect(toolPresentation(call, t, true).label).toBe("tool_ask_user_done");
    // An external server named "questions" keeps its own tool's name.
    expect(
      toolPresentation(
        { ...call, providerMetadata: { eneo: { server_name: "questions", is_internal: false } } },
        t,
        false
      ).label
    ).toBe("Ask user");
  });

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

  it("names a function by its purpose and hides a provider built into Eneo", () => {
    const bundled = {
      toolName: "create_document",
      providerMetadata: {
        eneo: {
          server_name: "Create a file",
          title: "Create document",
          purpose: "file_creation",
          is_internal: false,
          is_bundled: true
        }
      }
    };
    expect(toolPresentation(bundled, t, false)).toEqual({
      label: "tool_file_creation",
      server: "file_creation",
      provider: null
    });
    expect(toolPresentation(bundled, t, true).label).toBe("tool_file_creation_done");

    const external = {
      toolName: "plot",
      providerMetadata: { eneo: { server_name: "Plot Inc", purpose: "charts", is_internal: false } }
    };
    expect(toolPresentation(external, t, true)).toEqual({
      label: "tool_charts_done",
      server: "charts",
      provider: "Plot Inc"
    });
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

  it("keeps its own title and arguments when named flows", () => {
    const call = {
      toolName: "read_flow_suggestions",
      input: { include_runs: true },
      providerMetadata: {
        eneo: { server_name: "flows", title: "Read flow suggestions", is_internal: false }
      }
    };
    expect(toolPresentation(call, t, true)).toEqual({
      label: "Read flow suggestions",
      server: "flows",
      provider: null
    });
    expect(toolTarget(call, t)).toBe("include_runs: true");
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

  it("lets what a live call returned win over what its announcement knew", async () => {
    // The input chunk announces the call before it runs: no result status and
    // no data yet. The output chunk carries both, and a run card drawn from
    // the data must appear while the answer streams, not first on a reload.
    const { eneoToolMetadata } = await import("./tool-presentation");
    const metadata = eneoToolMetadata({
      toolName: "run_flow",
      callProviderMetadata: {
        eneo: {
          server_name: "flows",
          is_internal: true,
          result_status: null,
          structured_content: null
        }
      },
      resultProviderMetadata: {
        eneo: {
          server_name: "flows",
          is_internal: true,
          result_status: "succeeded",
          structured_content: { flow_id: "flow-1", run_id: "run-1" }
        }
      }
    });
    expect(metadata.result_status).toBe("succeeded");
    expect(metadata.structured_content).toEqual({ flow_id: "flow-1", run_id: "run-1" });
    expect(metadata.is_internal).toBe(true);
  });
});

describe("toolTarget", () => {
  const files = [{ id: "3021a3ac-86a3-4bb8-a0dc-d3c600f994e7", name: "kostnader-2025.xlsx" }];
  const read = (offset: number) => ({
    toolName: "read_file",
    input: {
      url: "http://host.docker.internal:8123/api/v1/files/3021a3ac-86a3-4bb8-a0dc-d3c600f994e7/original/download/?token=REDACTED",
      offset
    },
    providerMetadata: { eneo: { server_name: "files", is_internal: true } }
  });

  it("names the attachment and the position for a read, never the signed url", () => {
    expect(toolTarget(read(0), t, { files })).toBe(
      "kostnader-2025.xlsx · chat_tool_read_from_start"
    );
    expect(toolTarget(read(16384), t, { files, locale: "sv" })).toBe(
      "kostnader-2025.xlsx · chat_tool_read_from:16\u00a0384"
    );
    // A file the session does not list still shows no url.
    expect(toolTarget(read(0), t, { files: [] })).toBe(
      "internal_files_server · chat_tool_read_from_start"
    );
  });

  it("shows the query for searches and the readable arguments otherwise", () => {
    expect(
      toolTarget(
        {
          toolName: "search",
          input: { query: "lou tröskelvärden" },
          providerMetadata: { eneo: { server_name: "web_search", purpose: "web_search" } }
        },
        t
      )
    ).toBe("lou tröskelvärden");
    expect(
      toolTarget(
        {
          toolName: "create_issue",
          input: { project: "LOU", summary: "x".repeat(60), labels: ["a"] },
          providerMetadata: { eneo: { server_name: "jira", is_internal: false } }
        },
        t
      )
    ).toBe(`project: LOU · summary: ${"x".repeat(48)}…`);
  });
});

/** The loopback flows server, as the flow authoring chat calls it. */
describe("Eneo's flows server", () => {
  const svT = createTranslator({ locale: "sv", messages: sv as Record<string, string> });
  const enT = createTranslator({ locale: "en", messages: en as Record<string, string> });
  const flows = (toolName: string, input: Record<string, unknown> = {}) => ({
    toolName,
    input,
    providerMetadata: { eneo: { server_name: "flows", is_internal: true } }
  });
  const tools = [
    "read_flow",
    "update_flow_settings",
    "read_step_assistant",
    "update_step",
    "update_steps",
    "add_step",
    "move_step",
    "remove_step",
    "publish_flow",
    "unpublish_flow",
    "read_tool_options",
    "read_flow_suggestions",
    "apply_flow_suggestions",
    "dismiss_flow_suggestion",
    "run_flow",
    "read_run",
    "cancel_run",
    "read_review",
    "review_run"
  ];

  it("names each call in plain words while it runs and once it is done", () => {
    const suggestions = flows("read_flow_suggestions", { offset: 0 });
    expect(toolPresentation(suggestions, svT, false)).toEqual({
      label: "Läser förslagen",
      server: "Flöden"
    });
    expect(toolPresentation(suggestions, svT, true).label).toBe("Läste förslagen");
    expect(toolPresentation(flows("update_step"), svT, false).label).toBe("Ändrar steg");
    expect(toolPresentation(flows("update_step"), svT, true).label).toBe("Ändrade steg");
    expect(toolPresentation(suggestions, enT, true)).toEqual({
      label: "Read the suggestions",
      server: "Flows"
    });
  });

  it("says when the suggestions count the latest runs", () => {
    const measured = flows("read_flow_suggestions", { include_runs: true, offset: 0 });
    expect(toolPresentation(measured, svT, false).label).toBe(
      "Läser förslagen och räknar med de senaste körningarna"
    );
    expect(toolPresentation(measured, svT, true).label).toBe(
      "Läste förslagen och räknade med de senaste körningarna"
    );
    expect(
      toolPresentation(flows("read_flow_suggestions", { include_runs: false }), svT, true).label
    ).toBe("Läste förslagen");
  });

  it("has both forms of every label in both languages", () => {
    const calls = [
      ...tools.map((tool) => flows(tool)),
      flows("read_flow_suggestions", { include_runs: true })
    ];
    for (const call of calls) {
      for (const done of [false, true]) {
        const key = toolPresentation(call, t, done).label;
        expect(key).toMatch(/^tool_flows_/);
        expect(sv).toHaveProperty(key);
        expect(en).toHaveProperty(key);
      }
    }
  });

  it("names a tool it has no label for from its title, under the server's own name", () => {
    const call = {
      toolName: "export_flow",
      providerMetadata: { eneo: { server_name: "flows", title: "Export flow", is_internal: true } }
    };
    expect(toolPresentation(call, svT, true)).toEqual({
      label: "Export flow",
      server: "flows",
      provider: null
    });
  });

  it("shows no internal arguments under the label, only a new step's name", () => {
    expect(
      toolTarget(flows("read_flow_suggestions", { include_runs: true, offset: 0 }), t)
    ).toBeNull();
    expect(
      toolTarget(
        flows("update_step", {
          expected_revision: 4,
          step_id: "0b0e4c5e-6f0a-4a57-9a3c-1f2a3b4c5d6e",
          changes: { user_description: "Sammanfatta" }
        }),
        t
      )
    ).toBeNull();
    expect(
      toolTarget(flows("add_step", { expected_revision: 4, name: "Sammanfatta ärendet" }), t)
    ).toBe("Sammanfatta ärendet");
    expect(toolTarget(flows("add_step", { name: "  " }), t)).toBeNull();
  });
});
