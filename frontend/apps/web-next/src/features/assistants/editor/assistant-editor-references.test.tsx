// @vitest-environment jsdom
import { ChatTokenizedText } from "@astryxdesign/core/Chat";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Composer } from "@/features/chat/composer";
import { useAttachments } from "@/features/chat/use-attachments";
import type { HelperAdapter } from "@/features/helper/helper-adapter";
import type { HelperPanelClose } from "@/features/helper/helper-panel";
import type { Space } from "@/features/spaces/space";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { reportResize, setViewport } from "@/test/setup-dom";
import { AssistantEditor } from "./assistant-editor";
import { assistantHelperKeys } from "./assistant-helper-api";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space) };
});
const state = vi.hoisted(() => ({
  space: null as unknown as Space,
  sent: [] as string[],
  // A message in the chat that points at two settings, one of them not shown to the person.
  message: "Se @[Namn](setting:name) och @[Webbwidget](setting:section:widget)."
}));
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
// The sections the tests read have a heading and a field; the rest are left out.
vi.mock("./general-section", async () => {
  const { SettingsGroup } = await import("@/components/composites/settings-rows");
  return {
    GeneralSection: () => (
      <SettingsGroup title="Allmänt">
        <label htmlFor="assistant-name">Namn</label>
        <input id="assistant-name" />
      </SettingsGroup>
    )
  };
});
vi.mock("./security-section", async () => {
  const { SettingsGroup } = await import("@/components/composites/settings-rows");
  return {
    SecuritySection: () => (
      <SettingsGroup title="Säkerhet och integritet">
        <label htmlFor="assistant-retention-days">Dagar</label>
        <input id="assistant-retention-days" disabled />
      </SettingsGroup>
    )
  };
});
// The prompt's own section is tested on its own; here it is the way into the helper the editor gives it.
vi.mock("./instructions-section", () => ({
  InstructionsSection: ({ onAskPrompt }: { onAskPrompt?: () => void }) =>
    onAskPrompt ? (
      <button type="button" onClick={onAskPrompt}>
        Hjälp mig skriva instruktionerna
      </button>
    ) : null
}));
vi.mock("./knowledge-section", () => ({ KnowledgeSection: () => null }));
vi.mock("./mcp-section", () => ({ McpSection: () => null }));
vi.mock("./capabilities-section", () => ({
  CapabilitiesSection: () => null,
  selectedCapabilities: () => []
}));
vi.mock("./attachments-section", () => ({ AttachmentsSection: () => null }));
vi.mock("./publishing-section", () => ({ PublishingSection: () => null }));
// The helper panel is the helper feature's: here it is the chat's real
// composer on the adapter's references, and one message drawn with them.
vi.mock("@/features/helper/helper-panel", () => ({
  HelperPanel: (props: { adapter: HelperAdapter; close: HelperPanelClose; open?: boolean }) => (
    <HelperChat {...props} />
  )
}));

function HelperChat({
  adapter,
  close,
  open
}: {
  adapter: HelperAdapter;
  close: HelperPanelClose;
  open?: boolean;
}) {
  const [value, setValue] = useState("");
  const attachments = useAttachments({ type: "assistant", id: "helper", name: "Hjälpen" });
  const references = adapter.references!;
  return (
    <div data-testid="helper-chat" data-open={String(open)}>
      <button type="button" onClick={close.onClose}>
        {close.label}
      </button>
      <p>
        <ChatTokenizedText tokens={references.tokens!(state.message)}>
          {state.message}
        </ChatTokenizedText>
      </p>
      <Composer
        value={value}
        onChange={setValue}
        onSubmit={() => state.sent.push(value)}
        busy={false}
        onStop={vi.fn()}
        label="Meddelande till hjälpassistenten"
        placeholder="Fråga om assistenten…"
        attachments={attachments}
        onOpenFileDialog={vi.fn()}
        triggers={references.triggers}
        onInput={references.onComposer}
        footerActions={adapter.footerActions}
      />
    </div>
  );
}

afterEach(() => {
  cleanup();
  state.sent = [];
  setViewport("desktop");
});

const ASSISTANT = {
  id: "assistant-1",
  name: "Bygglov",
  permissions: ["read", "edit"],
  groups: [],
  websites: [],
  integration_knowledge_list: [],
  mcp_servers: [],
  attachments: [],
  prompt: null,
  completion_model: null,
  completion_model_kwargs: {},
  effective_config: null
};

function renderEditor({
  space = makeSpace(),
  assistant = {},
  availability = { available: true }
}: {
  space?: Space;
  assistant?: Record<string, unknown>;
  availability?: { available: boolean; reason?: string };
} = {}) {
  state.space = space;
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", "assistant-1"], { ...ASSISTANT, ...assistant });
  queryClient.setQueryData(assistantHelperKeys.availability("assistant-1"), availability);
  return renderInApp(<AssistantEditor assistantId="assistant-1" />, {
    queryClient,
    route: "/spaces/space-1/assistants/assistant-1/edit"
  });
}

const composerField = () =>
  screen.getByRole("combobox", { name: "Meddelande till hjälpassistenten" });
const pillsInComposer = () =>
  [...composerField().querySelectorAll("[data-astryx-token-value]")].map((token) =>
    token.getAttribute("data-astryx-token-value")
  );
const helperPanel = () => screen.queryByRole("complementary", { name: "Hjälpassistent" });
const headerToggle = () =>
  screen
    .getAllByRole("button", { name: "Hjälpassistent" })
    .find((button) => button.closest("header"))!;

describe("'Fråga' on each section", () => {
  it("is a quiet button at the end of each section's heading row, named for its section", async () => {
    const { container } = renderEditor();
    const ask = screen.getByRole("button", { name: "Fråga hjälpassistenten om AI-inställningar" });
    expect(ask.textContent).toBe("Fråga");
    // In the heading row of the section it names, after the heading.
    const section = container.querySelector("#ai")!;
    expect(section.querySelector("[data-settings-group-end]")?.contains(ask)).toBe(true);
    expect(within(section as HTMLElement).getByRole("heading").textContent).toBe(
      "AI-inställningar"
    );
    expect(
      screen
        .getAllByRole("button", { name: /^Fråga hjälpassistenten om / })
        .map((button) => button.getAttribute("aria-label"))
    ).toEqual([
      "Fråga hjälpassistenten om Allmänt",
      "Fråga hjälpassistenten om AI-inställningar",
      "Fråga hjälpassistenten om Säkerhet och integritet"
    ]);
    await expectNoAxeViolations(container);
  });

  it("opens the helper with a reference to the section in its composer, focused, and sends nothing", async () => {
    renderEditor();
    expect(helperPanel()).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Fråga hjälpassistenten om AI-inställningar" })
    );

    expect(helperPanel()).toBeTruthy();
    await waitFor(() =>
      expect(pillsInComposer()).toEqual(["@[AI-inställningar](setting:section:ai)"])
    );
    expect(within(composerField()).getByText("AI-inställningar")).toBeTruthy();
    expect(document.activeElement).toBe(composerField());
    expect(headerToggle().getAttribute("aria-pressed")).toBe("true");
    expect(state.sent).toEqual([]);
  });

  it("adds to the composer of a helper already open", async () => {
    renderEditor();
    act(() => reportResize(document.querySelector("[data-companion-row]")!, { width: 1600 }));
    fireEvent.click(headerToggle());
    await waitFor(() => expect(composerField()).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Fråga hjälpassistenten om Allmänt" }));
    await waitFor(() => expect(pillsInComposer()).toEqual(["@[Allmänt](setting:section:general)"]));
    expect(document.activeElement).toBe(composerField());
  });

  it("is not offered while the helper is unavailable", () => {
    renderEditor({ availability: { available: false, reason: "no_model" } });
    expect(screen.getByRole("heading", { name: "AI-inställningar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Fråga hjälpassistenten/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Hjälp mig välja modell" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Hjälp mig skriva instruktionerna" })).toBeNull();
  });

  it("is not offered on the personal chat's own assistant", () => {
    renderEditor({
      space: makeSpace({
        overrides: {
          personal: true,
          default_assistant: { id: "assistant-1", name: "Bygglov", permissions: ["read"] }
        }
      })
    });
    expect(screen.getByRole("heading", { name: "AI-inställningar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Fråga hjälpassistenten/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Hjälp mig välja modell" })).toBeNull();
  });
});

describe("'Hjälp mig välja modell' under the chat model", () => {
  it("opens the helper with a question about the chat model in its composer", async () => {
    renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Hjälp mig välja modell" }));

    await waitFor(() =>
      expect(pillsInComposer()).toEqual(["@[Chattmodell](setting:completion_model)"])
    );
    // The pill ends the question, so what the person types next follows it.
    expect(composerField().textContent?.replace(/\s+/g, " ").trim()).toBe(
      "Hjälp mig välja Chattmodell"
    );
    expect(document.activeElement).toBe(composerField());
    expect(state.sent).toEqual([]);
  });

  it("is not offered to someone who may not change the model", () => {
    renderEditor({ assistant: { permissions: ["read"] } });
    expect(screen.getByRole("heading", { name: "AI-inställningar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Hjälp mig välja modell" })).toBeNull();
  });

  it("is not offered where a policy sets the model", () => {
    renderEditor({
      assistant: {
        effective_config: {
          models_enforced: true,
          locked_model: { id: "model-locked", name: "Policymodellen" },
          available_models: []
        }
      }
    });
    expect(screen.getByRole("heading", { name: "AI-inställningar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Hjälp mig välja modell" })).toBeNull();
  });
});

describe("'Hjälp mig skriva instruktionerna' beside the prompt", () => {
  const ask = () => screen.queryByRole("button", { name: "Hjälp mig skriva instruktionerna" });

  it("opens the helper with a request about the prompt in its composer", async () => {
    renderEditor();
    fireEvent.click(ask()!);

    await waitFor(() => expect(pillsInComposer()).toEqual(["@[Prompt](setting:prompt)"]));
    expect(composerField().textContent?.replace(/\s+/g, " ").trim()).toBe(
      "Hjälp mig skriva Prompt"
    );
    expect(document.activeElement).toBe(composerField());
    expect(state.sent).toEqual([]);
  });

  it("is not offered to someone who may not change the prompt", () => {
    renderEditor({ assistant: { permissions: ["read"] } });
    expect(screen.getByRole("heading", { name: "AI-inställningar" })).toBeTruthy();
    expect(ask()).toBeNull();
  });

  it("is not offered where a policy sets the prompt", () => {
    renderEditor({ assistant: { effective_config: { prompt_locked: true } } });
    expect(screen.getByRole("heading", { name: "AI-inställningar" })).toBeTruthy();
    expect(ask()).toBeNull();
  });
});

describe("The helper beside the settings", () => {
  it("is told when it is put away and shown again, staying mounted, so it shows the current conversation", async () => {
    renderEditor();
    act(() => reportResize(document.querySelector("[data-companion-row]")!, { width: 1600 }));
    fireEvent.click(headerToggle());
    const chat = await screen.findByTestId("helper-chat");
    expect(chat.getAttribute("data-open")).toBe("true");

    fireEvent.click(headerToggle());
    expect(screen.getByTestId("helper-chat")).toBe(chat);
    expect(chat.getAttribute("data-open")).toBe("false");
    fireEvent.click(headerToggle());
    expect(chat.getAttribute("data-open")).toBe("true");
  });
});

describe("A pill in the helper chat", () => {
  it("shows its setting beside the helper: focus moves to the field and the helper stays", async () => {
    renderEditor();
    act(() => reportResize(document.querySelector("[data-companion-row]")!, { width: 1600 }));
    fireEvent.click(headerToggle());

    fireEvent.click(await screen.findByRole("button", { name: "Namn" }));

    expect(document.activeElement).toBe(document.getElementById("assistant-name"));
    expect(helperPanel()).toBeTruthy();
  });

  it("closes a helper that covers the form first, and focus stays on the setting", async () => {
    renderEditor();
    // Before the row is measured the helper covers the form, which is inert under it.
    fireEvent.click(headerToggle());
    expect(document.getElementById("assistant-name")!.closest("[inert]")).not.toBeNull();

    fireEvent.click(await screen.findByRole("button", { name: "Namn" }));

    expect(helperPanel()).toBeNull();
    expect(headerToggle().getAttribute("aria-pressed")).toBe("false");
    expect(document.getElementById("assistant-name")!.closest("[inert]")).toBeNull();
    expect(document.activeElement).toBe(document.getElementById("assistant-name"));
  });

  it("focuses a section's heading for a setting whose field cannot take focus", async () => {
    state.message = "Se @[Gallring](setting:data_retention_days).";
    try {
      renderEditor();
      act(() => reportResize(document.querySelector("[data-companion-row]")!, { width: 1600 }));
      fireEvent.click(headerToggle());
      fireEvent.click(await screen.findByRole("button", { name: /Gallring/ }));
      expect(document.activeElement).toBe(
        screen.getByRole("heading", { name: "Säkerhet och integritet" })
      );
    } finally {
      state.message = "Se @[Namn](setting:name) och @[Webbwidget](setting:section:widget).";
    }
  });

  it("is plain text for what the form does not show this person", async () => {
    // Without edit rights there is no widget section.
    renderEditor({ assistant: { permissions: ["read"] } });
    fireEvent.click(headerToggle());
    const pill = await screen.findByRole("button", { name: "Namn" });
    expect(screen.queryByRole("button", { name: "Webbwidget" })).toBeNull();
    expect(pill.closest("p")?.textContent).toBe("Se Namn och Webbwidget.");
  });

  it("opens the setting's section on a phone, with the helper closed", async () => {
    setViewport("phone");
    renderEditor();
    fireEvent.click(screen.getAllByRole("button", { name: "Hjälpassistent" }).at(-1)!);

    fireEvent.click(await screen.findByRole("button", { name: "Namn" }));

    expect(helperPanel()).toBeNull();
    await waitFor(() =>
      expect(document.activeElement).toBe(document.getElementById("assistant-name"))
    );
    expect(document.querySelector("[data-editor-view]")?.getAttribute("data-editor-view")).toBe(
      "section"
    );
  });
});

describe("The composer's '@' button", () => {
  it("opens the menu of the settings the form shows", async () => {
    renderEditor();
    fireEvent.click(headerToggle());
    fireEvent.click(await screen.findByRole("button", { name: "Referera till en inställning" }));

    const menu = await screen.findByRole("listbox", { name: "Inställningar" });
    expect(
      within(menu)
        .getAllByRole("group")
        .map((group) => group.getAttribute("aria-label"))
    ).toEqual([
      "Allmänt",
      "Instruktioner",
      "Kunskap",
      "MCP-servrar",
      "Bilagor",
      "AI-inställningar",
      "Funktioner",
      "Säkerhet och integritet",
      "API-nycklar",
      "Webbwidget"
    ]);
  });
});
