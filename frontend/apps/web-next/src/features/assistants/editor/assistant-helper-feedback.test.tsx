// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ToolCallRecord, ToolPart } from "@/features/chat/side-panel/message-tool-calls";
import type { HelperAdapter } from "@/features/helper/helper-adapter";
import type { HelperPanelClose } from "@/features/helper/helper-panel";
import type { Space } from "@/features/spaces/space";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { renderInApp, testQueryClient } from "@/test/render";
import { reportResize, setViewport } from "@/test/setup-dom";
import { AssistantEditor } from "./assistant-editor";
import { assistantHelperKeys, type AssistantHelperAvailability } from "./assistant-helper-api";
import { CHAT_CHANGE_MARK_MS, chatChangeMarks } from "./assistant-helper-feedback";
import type { SettingReference } from "./setting-references";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const announce = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }));
const state = vi.hoisted(() => ({
  space: null as unknown as Space,
  assistant: {} as Record<string, unknown>,
  /** The adapter the editor gave its helper panel, as last rendered. */
  adapter: null as HelperAdapter | null,
  /** Tool calls whose cards the helper shows. */
  cards: [] as ToolCallRecord[]
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));
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
// The AI section's rows as the form draws them; the section itself is tested on its own.
vi.mock("./ai-section", async () => {
  const { SettingsGroup, SettingsRow } = await import("@/components/composites/settings-rows");
  return {
    AiSection: () => (
      <SettingsGroup title="AI-inställningar">
        <SettingsRow title="Chattmodell" htmlFor="assistant-completion-model">
          <input id="assistant-completion-model" />
        </SettingsRow>
        <SettingsRow title="Modellbeteende" htmlFor="assistant-model-behaviour">
          <input id="assistant-model-behaviour" />
        </SettingsRow>
      </SettingsGroup>
    )
  };
});
vi.mock("./instructions-section", () => ({ InstructionsSection: () => null }));
vi.mock("./knowledge-section", () => ({ KnowledgeSection: () => null }));
vi.mock("./mcp-section", () => ({ McpSection: () => null }));
vi.mock("./capabilities-section", () => ({
  CapabilitiesSection: () => null,
  selectedCapabilities: () => []
}));
vi.mock("./attachments-section", () => ({ AttachmentsSection: () => null }));
vi.mock("./publishing-section", () => ({ PublishingSection: () => null }));
vi.mock("./security-section", () => ({ SecuritySection: () => null }));
// The helper panel is the helper feature's (helper-panel.test.tsx): here it
// hands the test its adapter and draws the cards the chat would.
vi.mock("@/features/helper/helper-panel", () => ({
  HelperPanel: (props: { adapter: HelperAdapter; close: HelperPanelClose }) => (
    <HelperStub {...props} />
  )
}));

function HelperStub({ adapter, close }: { adapter: HelperAdapter; close: HelperPanelClose }) {
  useEffect(() => {
    state.adapter = adapter;
  });
  return (
    <div>
      <button type="button" onClick={close.onClose}>
        {close.label}
      </button>
      <label>
        Meddelande <textarea />
      </label>
      {state.cards.map((call) => (
        <div key={call.toolCallId}>{adapter.toolCards?.(call)}</div>
      ))}
    </div>
  );
}

const ID = "assistant-1";
const EDIT = "/spaces/space-1/assistants/assistant-1/edit";
const HAIKU = { id: "model-1", name: "claude-haiku" };
const OPUS = { id: "model-2", name: "claude-opus" };
const ASSISTANT = {
  id: ID,
  name: "Bygglov",
  description: "Svarar om bygglov.",
  permissions: ["read", "edit"],
  groups: [],
  websites: [],
  integration_knowledge_list: [],
  mcp_servers: [],
  attachments: [],
  prompt: { text: "Svara kort." },
  completion_model: HAIKU,
  completion_model_kwargs: { temperature: 0.7 },
  knowledge_mode: "tool",
  inline_file_text: false,
  effective_config: null,
  icon_id: null
};

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
const refused = () => ({
  error: { message: "Tjänsten svarar inte." },
  response: new Response(null, { status: 500 })
});

function toolCall(
  toolName: string,
  structuredContent: Record<string, unknown>,
  { serverName = "assistant", id = toolName } = {}
): ToolCallRecord {
  return {
    toolCallId: `call-${id}`,
    toolName,
    state: "output-available",
    input: {},
    serverName,
    title: null,
    purpose: null,
    isInternal: true,
    isBundled: false,
    appView: null,
    approved: null,
    resultStatus: "succeeded",
    generatedFileIds: [],
    structuredContent,
    part: {} as ToolPart
  };
}

type Change = { field: string; before: unknown; after: unknown };
const update = (changes: Change[], options: { serverName?: string; target?: string } = {}) =>
  toolCall(
    "update_assistant",
    { target_id: options.target ?? ID, changes, undo: {} },
    { serverName: options.serverName }
  );

function renderEditor({
  availability = { available: true },
  route = EDIT,
  assistant = {}
}: {
  availability?: AssistantHelperAvailability | null;
  route?: string;
  assistant?: Record<string, unknown>;
} = {}) {
  state.space = makeSpace();
  state.assistant = { ...ASSISTANT, ...assistant };
  api.GET.mockImplementation(async (path: string) =>
    path.endsWith("/availability") ? new Promise(() => {}) : ok(state.assistant)
  );
  api.POST.mockImplementation(async (_path: string, init: { body: Record<string, unknown> }) => {
    const { completion_model, ...rest } = init.body;
    state.assistant = {
      ...state.assistant,
      ...rest,
      ...(completion_model ? { completion_model: OPUS } : {})
    };
    return ok(state.assistant);
  });
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", ID], state.assistant);
  if (availability) {
    queryClient.setQueryData(assistantHelperKeys.availability(ID), availability);
  }
  return renderInApp(<AssistantEditor assistantId={ID} />, { queryClient, route });
}

const headerToggle = () =>
  screen
    .getAllByRole("button", { name: "Hjälpassistent" })
    .find((button) => button.closest("header"))!;
const rail = () => document.querySelector<HTMLElement>("[data-editor-rail]")!;
const aside = () => screen.queryByRole("complementary", { name: "Hjälpassistent" });

/** Opens the helper beside the form, where the row has room for both. */
function openHelperBeside() {
  act(() => reportResize(document.querySelector("[data-companion-row]")!, { width: 1600 }));
  fireEvent.click(headerToggle());
}

/** Whether the form's row for the field labelled `label` is marked as changed from the chat. */
function marked(label: string) {
  const row = screen
    .getByText(label, { selector: "label" })
    .closest<HTMLElement>("[class*='scroll-mt-32']")!;
  return within(row).queryByText("Ändrad från chatten") !== null;
}

const announced = (text: string) => announce.mock.calls.filter(([said]) => said === text).length;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
  state.adapter = null;
  state.cards = [];
  setViewport("desktop");
});

describe("Changes from the chat, in the form", () => {
  it("marks the rows a change of the helper touched and counts them on the section's link, says so once and lets them go after 8 seconds", () => {
    renderEditor();
    openHelperBeside();
    vi.useFakeTimers();

    act(() =>
      state.adapter!.onToolCallFinished!(
        update([
          { field: "completion_model", before: HAIKU, after: OPUS },
          { field: "completion_model_kwargs.temperature", before: 0.7, after: 0.2 },
          // Given as changed, but the same before and after: nothing changed.
          { field: "name", before: "Bygglov", after: "Bygglov" }
        ])
      )
    );

    expect(marked("Chattmodell")).toBe(true);
    expect(marked("Modellbeteende")).toBe(true);
    expect(marked("Namn")).toBe(false);
    expect(marked("Beskrivning")).toBe(false);
    expect(
      within(rail()).getByRole("link", { name: /^AI-inställningar ?, 2 ändrade$/ })
    ).toBeTruthy();
    expect(within(rail()).getByRole("link", { name: "Allmänt" })).toBeTruthy();
    expect(announced("Hjälpassistenten ändrade Chattmodell och Modellbeteende.")).toBe(1);
    expect(announce.mock.calls.filter(([said]) => /ändrade/.test(String(said)))).toHaveLength(1);

    act(() => vi.advanceTimersByTime(CHAT_CHANGE_MARK_MS - 1));
    expect(marked("Chattmodell")).toBe(true);
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByText("Ändrad från chatten")).toBeNull();
    expect(within(rail()).getByRole("link", { name: "AI-inställningar" })).toBeTruthy();
  });

  it("marks nothing for another server's call, or a call about another assistant", () => {
    renderEditor();
    openHelperBeside();
    const change = [{ field: "name", before: "Bygglov", after: "Bygglovshjälpen" }];

    act(() => state.adapter!.onToolCallFinished!(update(change, { serverName: "flows" })));
    act(() => state.adapter!.onToolCallFinished!(update(change, { target: "assistant-2" })));

    expect(screen.queryByText("Ändrad från chatten")).toBeNull();
    expect(
      announce.mock.calls.filter(([said]) => /Hjälpassistenten ändrade/.test(String(said)))
    ).toHaveLength(0);
  });

  it("marks nothing for the person's own typing", async () => {
    renderEditor();
    openHelperBeside();
    const name = screen.getByRole("textbox", { name: "Namn" });

    fireEvent.change(name, { target: { value: "Bygglovshjälpen" } });
    fireEvent.blur(name);

    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(state.assistant.name).toBe("Bygglovshjälpen"));
    expect(screen.queryByText("Ändrad från chatten")).toBeNull();
  });

  it("marks what Använd changed, after saving what the form had pending, and says so once", async () => {
    state.cards = [
      toolCall("propose_changes", {
        target_id: ID,
        proposal: {
          changes: [{ field: "name", before: "Bygglov", after: "Bygglovshjälpen" }],
          update: { name: "Bygglovshjälpen" }
        }
      })
    ];
    renderEditor();
    openHelperBeside();
    // A description typed and not yet saved.
    fireEvent.change(screen.getByRole("textbox", { name: "Beskrivning" }), {
      target: { value: "Svarar om bygglov och marklov." }
    });

    fireEvent.click(await screen.findByRole("button", { name: "Använd" }));

    await waitFor(() => expect(marked("Namn")).toBe(true));
    expect(api.POST.mock.calls.map(([, init]) => init.body)).toEqual([
      { description: "Svarar om bygglov och marklov." },
      { name: "Bygglovshjälpen" }
    ]);
    // The person's own description is saved, not marked.
    expect(marked("Beskrivning")).toBe(false);
    expect(within(rail()).getByRole("link", { name: /^Allmänt ?, 1 ändrad$/ })).toBeTruthy();
    expect(announced("Du använde förslaget och ändrade Namn.")).toBe(1);
    expect(announced("Ändringen är sparad.")).toBe(0);
  });

  it("holds Använd when what the form had pending cannot be saved, and says so at the card", async () => {
    state.cards = [
      toolCall("propose_changes", {
        target_id: ID,
        proposal: {
          changes: [{ field: "name", before: "Bygglov", after: "Bygglovshjälpen" }],
          update: { name: "Bygglovshjälpen" }
        }
      })
    ];
    renderEditor();
    openHelperBeside();
    api.POST.mockImplementationOnce(async () => refused());
    fireEvent.change(screen.getByRole("textbox", { name: "Beskrivning" }), {
      target: { value: "Svarar om bygglov och marklov." }
    });

    fireEvent.click(await screen.findByRole("button", { name: "Använd" }));

    expect(
      await screen.findByText("Inställningarna kunde inte sparas, så ändringen gjordes inte.")
    ).toBeTruthy();
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(api.POST.mock.calls[0]![1].body).toEqual({
      description: "Svarar om bygglov och marklov."
    });
    // The form says the save failed where it always does.
    expect(screen.getAllByText("Kunde inte spara ändringarna").length).toBeGreaterThan(0);
    expect(screen.queryByText("Ändrad från chatten")).toBeNull();
  });

  it("marks what Ångra changed back, and says so once", async () => {
    state.cards = [
      toolCall("update_assistant", {
        target_id: ID,
        changes: [{ field: "name", before: "Bygglov", after: "Bygglovshjälpen" }],
        undo: { name: "Bygglov" }
      })
    ];
    renderEditor({ assistant: { name: "Bygglovshjälpen" } });
    openHelperBeside();

    fireEvent.click(await screen.findByRole("button", { name: "Ångra" }));

    await waitFor(() => expect(marked("Namn")).toBe(true));
    expect(api.POST.mock.calls.map(([, init]) => init.body)).toEqual([{ name: "Bygglov" }]);
    expect(announced("Du ångrade ändringen av Namn.")).toBe(1);
  });
});

describe("Before a message goes to the helper", () => {
  it("saves what the form has pending, then lets the message go", async () => {
    renderEditor();
    openHelperBeside();
    fireEvent.change(screen.getByRole("textbox", { name: "Beskrivning" }), {
      target: { value: "Svarar om bygglov och marklov." }
    });

    let held: string | null | undefined;
    await act(async () => {
      held = await state.adapter!.beforeSend!();
    });

    expect(held).toBeNull();
    expect(api.POST.mock.calls.map(([, init]) => init.body)).toEqual([
      { description: "Svarar om bygglov och marklov." }
    ]);
  });

  it("holds the message when that save fails, and says why", async () => {
    renderEditor();
    openHelperBeside();
    api.POST.mockImplementationOnce(async () => refused());
    fireEvent.change(screen.getByRole("textbox", { name: "Beskrivning" }), {
      target: { value: "Svarar om bygglov och marklov." }
    });

    let held: string | null | undefined;
    await act(async () => {
      held = await state.adapter!.beforeSend!();
    });

    expect(held).toBe(
      "Inställningarna kunde inte sparas, så meddelandet skickades inte. Rätta det som inte sparades och skicka igen."
    );
    expect(screen.getAllByText("Kunde inte spara ändringarna").length).toBeGreaterThan(0);
  });
});

describe("The helper's one mode", () => {
  it("has no mode to pick: the helper proposes and never writes the form by itself", () => {
    renderEditor();
    openHelperBeside();

    expect(state.adapter!.modes).toBeNull();
  });
});

describe("Escape and the helper", () => {
  it("closes a helper that covers the form, focus back on the toggle", () => {
    renderEditor();
    // Before the row is measured the helper covers the form.
    const toggle = headerToggle();
    toggle.focus();
    fireEvent.click(toggle);
    expect(document.querySelector("[data-companion]")?.getAttribute("data-companion")).toBe(
      "cover"
    );

    fireEvent.keyDown(screen.getByRole("textbox", { name: "Meddelande" }), { key: "Escape" });
    expect(aside()).toBeNull();
    expect(document.activeElement).toBe(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
  });

  it("leaves a helper beside the form open", () => {
    renderEditor();
    openHelperBeside();
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Meddelande" }), { key: "Escape" });
    expect(aside()).not.toBeNull();
  });
});

describe("The helper's toggle in a phone's section bar", () => {
  const sectionBar = () => document.querySelector<HTMLElement>("[data-phone-page-bar]")!;

  it("is there in a section, and opens the helper", () => {
    setViewport("phone");
    renderEditor({ route: `${EDIT}?section=general` });
    expect(document.querySelector("[data-editor-view]")?.getAttribute("data-editor-view")).toBe(
      "section"
    );

    const toggle = within(sectionBar()).getByRole("button", { name: "Hjälpassistent" });
    fireEvent.click(toggle);
    expect(aside()).not.toBeNull();
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
  });

  it.each([
    ["no model in the space", { available: false, reason: "no_model" }],
    ["no right to edit", { available: false, reason: "no_edit_rights" }],
    ["an assistant set up elsewhere", { available: false, reason: "not_supported" }],
    ["an answer not known yet", null]
  ] as const)("is not there for %s", (_case, availability) => {
    setViewport("phone");
    renderEditor({ route: `${EDIT}?section=general`, availability });
    expect(within(sectionBar()).queryByRole("button", { name: "Hjälpassistent" })).toBeNull();
  });
});

describe("chatChangeMarks", () => {
  const reference = (
    key: string,
    section: SettingReference["section"],
    control?: string
  ): [string, SettingReference] => [
    key,
    { key, section, sectionLabel: section, label: key, value: "", control }
  ];

  it("marks each setting's row once and counts the settings per section, leaving out what the form does not show", () => {
    const references = new Map([
      reference("name", "general", "assistant-name"),
      reference("completion_model", "ai", "assistant-completion-model"),
      reference("completion_model_kwargs", "ai", "assistant-model-behaviour"),
      reference(
        "completion_model_kwargs.reasoning_effort",
        "ai",
        "assistant-kwarg-reasoning_effort"
      ),
      reference("completion_model_kwargs.verbosity", "ai", "assistant-kwarg-verbosity")
    ]);

    expect(
      chatChangeMarks(
        [
          "name",
          // The temperature is the behaviour's row.
          "completion_model_kwargs.temperature",
          // The model's own settings share one row.
          "completion_model_kwargs.reasoning_effort",
          "completion_model_kwargs.verbosity",
          // Not offered by the model, or not in the form: neither marked nor counted.
          "completion_model_kwargs.top_p",
          "prompt"
        ],
        references
      )
    ).toEqual({
      rows: new Set(["assistant-name", "assistant-model-behaviour", "assistant-model-settings"]),
      sections: new Map([
        ["general", 1],
        ["ai", 3]
      ])
    });
  });
});
