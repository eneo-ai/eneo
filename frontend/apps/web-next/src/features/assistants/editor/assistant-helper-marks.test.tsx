// @vitest-environment jsdom
import { ChatTokenizedText } from "@astryxdesign/core/Chat";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ToolCallRecord, ToolPart } from "@/features/chat/side-panel/message-tool-calls";
import type { HelperAdapter } from "@/features/helper/helper-adapter";
import type { Space } from "@/features/spaces/space";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { renderInApp, testQueryClient } from "@/test/render";
import { reportResize, setViewport } from "@/test/setup-dom";
import { AssistantEditor } from "./assistant-editor";
import { assistantHelperKeys } from "./assistant-helper-api";
import type { Assistant } from "./use-assistant";

/**
 * The marks a change from the helper chat leaves on the settings it reaches
 * beyond the first ones, in the editor with the sections that show them:
 * the rows of the knowledge, the result ranking, the MCP servers, each
 * function, the document template, retention, insights and publishing, and
 * their sections' links; and the pills that show the ranking and the
 * template rows.
 */

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const announce = vi.hoisted(() => vi.fn());
const state = vi.hoisted(() => ({
  space: null as unknown as Space,
  assistant: {} as Record<string, unknown>,
  adapter: null as HelperAdapter | null
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => announce
}));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space) };
});
vi.mock("@/features/skills/use-can-attach-skills", () => ({ useCanAttachSkills: () => false }));
vi.mock("@/features/api-keys/resource-api-keys-section", () => ({
  ResourceApiKeysSection: () => null
}));
vi.mock("@/features/widget/admin/assistant-widget-section", () => ({
  AssistantWidgetSection: () => null
}));
vi.mock("./use-assistant-ai-draft", () => ({
  useAssistantAiDraft: () => ({
    modelId: "",
    kwargs: {},
    model: null,
    toolModel: null,
    effectiveModel: null,
    confirmed: true,
    isError: false,
    persist: vi.fn(),
    changeModel: vi.fn(),
    changeKwargs: vi.fn()
  })
}));
vi.mock("./general-section", () => ({ GeneralSection: () => null }));
vi.mock("./instructions-section", () => ({ InstructionsSection: () => null }));
vi.mock("./attachments-section", () => ({ AttachmentsSection: () => null }));
vi.mock("./ai-section", () => ({ AiSection: () => null }));
// The knowledge pickers are the knowledge feature's: here the section is its
// knowledge row and the real result ranking row.
vi.mock("./knowledge-section", async () => {
  const { SettingsGroup, SettingsRow } = await import("@/components/composites/settings-rows");
  const { RerankerRow } = await import("./reranker-row");
  return {
    KnowledgeSection: ({ assistant }: { assistant: Assistant }) => (
      <SettingsGroup title="Kunskap">
        <SettingsRow id="assistant-knowledge" title="Kunskap">
          <span>Bygglov</span>
        </SettingsRow>
        <RerankerRow assistant={assistant} />
      </SettingsGroup>
    )
  };
});
vi.mock("@/features/helper/helper-panel", () => ({
  HelperPanel: ({ adapter }: { adapter: HelperAdapter }) => <HelperStub adapter={adapter} />
}));

/** Hands the test the adapter, and draws one message with its references as the chat would. */
function HelperStub({ adapter }: { adapter: HelperAdapter }) {
  useEffect(() => {
    state.adapter = adapter;
  });
  const message =
    "Se @[Rankning av träffar](setting:rerank_model_id) och @[Dokumentmall](setting:document_template).";
  return (
    <p>
      <ChatTokenizedText tokens={adapter.references!.tokens!(message)}>{message}</ChatTokenizedText>
    </p>
  );
}

const ID = "assistant-1";
const TOOLS_MODEL = { id: "model-1", name: "claude-haiku", supports_tool_calling: true };
const RERANKER = {
  id: "rerank-1",
  name: "multilingual-rerank",
  nickname: "Flerspråkig rankning",
  can_access: true,
  meets_security_classification: true
};
const SERVER = {
  id: "server-1",
  name: "Ärenden",
  description: null,
  is_enabled: true,
  purpose: "custom",
  tools: [{ id: "tool-1", name: "search_cases", is_enabled: true }]
};
const ASSISTANT = {
  id: ID,
  name: "Bygglov",
  description: null,
  permissions: ["read", "edit", "publish", "insight_toggle"],
  groups: [],
  websites: [],
  integration_knowledge_list: [],
  mcp_servers: [SERVER],
  mcp_tools: [],
  enabled_capabilities: ["web_search", "file_creation"],
  document_template: { mode: "builtin", template_id: null },
  rerank_model_id: "rerank-1",
  data_retention_days: 30,
  insight_enabled: true,
  published: true,
  attachments: [],
  prompt: { text: "Svara kort." },
  completion_model: TOOLS_MODEL,
  completion_model_kwargs: {},
  knowledge_mode: "tool",
  inline_file_text: false,
  effective_config: null,
  icon_id: null
};

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });

function toolCall(
  toolName: string,
  changes: { field: string; before: unknown; after: unknown }[]
): ToolCallRecord {
  return {
    toolCallId: `call-${toolName}`,
    toolName,
    state: "output-available",
    input: {},
    serverName: "assistant",
    title: null,
    purpose: null,
    isInternal: true,
    isBundled: false,
    appView: null,
    approved: null,
    resultStatus: "succeeded",
    generatedFileIds: [],
    structuredContent: {
      target_id: ID,
      changes,
      undo: toolName === "update_assistant" ? {} : null
    },
    part: {} as ToolPart
  };
}

function renderEditor() {
  state.space = makeSpace({
    overrides: {
      completion_models: [TOOLS_MODEL],
      mcp_servers: [SERVER],
      enabled_capabilities: ["web_search", "charts", "file_creation"]
    }
  });
  state.assistant = { ...ASSISTANT };
  const models = { rerank_models: [RERANKER] };
  api.GET.mockImplementation(async (path: string) => {
    if (path.endsWith("/availability")) return new Promise(() => {});
    if (path === "/api/v1/ai-models/") return ok(models);
    if (path === "/api/v1/document-templates/available/") return ok({ items: [] });
    return ok(state.assistant);
  });
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", ID], state.assistant);
  queryClient.setQueryData(["ai-models", "space-1"], models);
  queryClient.setQueryData(assistantHelperKeys.availability(ID), { available: true });
  renderInApp(<AssistantEditor assistantId={ID} />, {
    queryClient,
    route: "/spaces/space-1/assistants/assistant-1/edit"
  });
  // The helper beside the form, so its adapter is handed over.
  act(() => reportResize(document.querySelector("[data-companion-row]")!, { width: 1600 }));
  fireEvent.click(
    screen.getAllByRole("button", { name: "Hjälpassistent" }).find((b) => b.closest("header"))!
  );
}

const MARK = "Ändrad från chatten";
/** Whether the element `id` names, or the row around it, carries the mark. */
const markedAt = (id: string, around = "[class*='scroll-mt-32']") => {
  const element = document.getElementById(id)!;
  const row = element.closest<HTMLElement>(around) ?? element;
  return within(row).queryByText(MARK) !== null;
};
const functionCard = (purpose: string) =>
  within(document.getElementById(`assistant-${purpose}`)!.closest<HTMLElement>(".rounded-lg")!);
const rail = () => document.querySelector<HTMLElement>("[data-editor-rail]")!;
const announced = (text: string) => announce.mock.calls.filter(([said]) => said === text).length;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  state.adapter = null;
  setViewport("desktop");
});

describe("Marks for the rest of the settings", () => {
  it("marks the knowledge, the result ranking, the MCP servers and each function switched, and counts them per section", () => {
    renderEditor();

    act(() =>
      state.adapter!.onToolCallFinished!(
        toolCall("update_assistant", [
          { field: "groups", before: [], after: [{ id: "c1", name: "Bygglov" }] },
          {
            field: "rerank_model_id",
            before: null,
            after: { id: "rerank-1", name: "Flerspråkig rankning" }
          },
          {
            field: "mcp_tools",
            before: [],
            after: [{ id: "tool-1", name: "search_cases", is_enabled: false }]
          },
          {
            field: "enabled_capabilities",
            before: [{ id: "file_creation", name: "file creation" }],
            after: [
              { id: "file_creation", name: "file creation" },
              { id: "web_search", name: "web search" }
            ]
          }
        ])
      )
    );

    expect(markedAt("assistant-knowledge")).toBe(true);
    expect(markedAt("reranker")).toBe(true);
    expect(within(document.getElementById("mcp")!).getByText(MARK)).toBeTruthy();
    // The function switched, not the one beside it.
    expect(functionCard("web_search").queryByText(MARK)).not.toBeNull();
    expect(functionCard("file_creation").queryByText(MARK)).toBeNull();
    expect(within(rail()).getByRole("link", { name: /^Kunskap ?, 2 ändrade$/ })).toBeTruthy();
    expect(within(rail()).getByRole("link", { name: /^MCP-servrar ?, 1 ändrad$/ })).toBeTruthy();
    expect(within(rail()).getByRole("link", { name: /^Funktioner ?, 1 ändrad$/ })).toBeTruthy();
    expect(
      announced(
        "Hjälpassistenten ändrade Kunskap, Rankning av träffar, MCP-servrar och Webbsökning."
      )
    ).toBe(1);
  });

  it("marks retention, insights, the document template and a publish, and counts them per section", () => {
    renderEditor();

    act(() =>
      state.adapter!.onToolCallFinished!(
        toolCall("update_assistant", [
          { field: "data_retention_days", before: null, after: 30 },
          { field: "insight_enabled", before: false, after: true },
          {
            field: "document_template",
            before: { mode: "default", template_id: null, name: null },
            after: { mode: "builtin", template_id: null, name: null }
          }
        ])
      )
    );
    act(() =>
      state.adapter!.onToolCallFinished!(
        toolCall("publish_assistant", [{ field: "published", before: false, after: true }])
      )
    );

    expect(markedAt("assistant-retention-days")).toBe(true);
    expect(markedAt("assistant-insights")).toBe(true);
    expect(markedAt("assistant-publish-status")).toBe(true);
    expect(
      within(document.getElementById("assistant-document-template")!).getByText(MARK)
    ).toBeTruthy();
    expect(
      within(rail()).getByRole("link", { name: /^Säkerhet och integritet ?, 1 ändrad$/ })
    ).toBeTruthy();
    expect(within(rail()).getByRole("link", { name: /^Publicering ?, 2 ändrade$/ })).toBeTruthy();
    expect(within(rail()).getByRole("link", { name: /^Funktioner ?, 1 ändrad$/ })).toBeTruthy();
    expect(
      announced(
        "Hjälpassistenten ändrade Gallring av konversationshistorik, Insikter och Dokumentmall."
      )
    ).toBe(1);
    expect(announced("Hjälpassistenten ändrade Status.")).toBe(1);
  });
});

describe("Pills for the result ranking and the document template", () => {
  it("show their rows in the form, focus on the row's control", async () => {
    renderEditor();

    fireEvent.click(await screen.findByRole("button", { name: "Rankning av träffar" }));
    expect(document.getElementById("reranker")!.contains(document.activeElement)).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Dokumentmall" }));
    expect(
      document.getElementById("assistant-document-template")!.contains(document.activeElement)
    ).toBe(true);
  });
});
