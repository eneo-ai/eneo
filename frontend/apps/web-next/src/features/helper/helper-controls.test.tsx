// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
// The flow is the helper's one target so far: its endpoints stand in for any target's.
import { flowHelperApi, flowKeys, type FlowAuthoringChat } from "@/features/flows/flows-api";
import {
  ConversationHistoryMenu,
  HelperChatSettings,
  NewConversationButton,
  helperChatModelId
} from "./helper-controls";

type Reply = { data?: unknown; error?: unknown; response: Response };

const ok = (data: unknown): Reply => ({ data, response: new Response(null, { status: 200 }) });
const refused = (status: number, body: Record<string, unknown>): Reply => ({
  error: { eneo_error_code: 9007, ...body },
  response: new Response(null, { status })
});

const state = vi.hoisted(() => ({
  announce: vi.fn(),
  reply: null as unknown,
  space: null as unknown
}));
const api = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(async () => state.reply),
  PATCH: vi.fn(async () => state.reply)
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return {
    useSpace: () => useSpaceFromQuery(() => state.space as ReturnType<typeof makeSpace>)
  };
});

const REASONING = {
  reasoning_effort: { supported: true, control: "select", options: ["low", "medium", "high"] }
};

const model = (id: string, nickname: string, overrides: Record<string, unknown> = {}) => ({
  id,
  name: id,
  nickname,
  org: "OpenAI",
  max_input_tokens: 128_000,
  max_output_tokens: 4096,
  is_deprecated: false,
  can_access: true,
  vision: false,
  reasoning: false,
  supports_tool_calling: true,
  ...overrides
});

const CHAT: FlowAuthoringChat = {
  flow_id: "flow-1",
  assistant_id: "assistant-chat",
  session_id: "session-1",
  editing: false,
  completion_model_id: null,
  reasoning_effort: null,
  default_completion_model_id: "model-standard"
};

beforeEach(() => {
  state.space = makeSpace({
    overrides: {
      completion_models: [
        model("model-standard", "Standardmodell"),
        model("model-strong", "Stark modell", {
          reasoning: true,
          supported_model_kwargs: REASONING
        }),
        model("model-plain", "Utan verktyg", { supports_tool_calling: false })
      ]
    }
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderControls(chat: FlowAuthoringChat = CHAT) {
  const onRefused = vi.fn();
  const queryClient = testQueryClient();
  queryClient.setQueryData(flowKeys.authoringChat(chat.flow_id), chat);
  const chatApi = flowHelperApi(chat.flow_id);
  const view = renderInApp(
    <div>
      <HelperChatSettings chat={chat} api={chatApi} onRefused={onRefused} />
      <NewConversationButton
        chat={chat}
        api={chatApi}
        description={messages.flows_chat_new_conversation_description}
        onRefused={onRefused}
      />
    </div>,
    { queryClient }
  );
  return { ...view, onRefused, queryClient };
}

/** Opens the settings popover the pickers live in. */
async function openSettings() {
  fireEvent.click(screen.getByRole("button", { name: "Chattinställningar" }));
  return screen.findByRole("dialog", { name: "Chattinställningar" });
}

describe("helperChatModelId", () => {
  const models = [model("a", "A"), model("b", "B")] as never[];

  it("is the person's own model while the space offers it, else the default", () => {
    const chat = { completion_model_id: "b", default_completion_model_id: "a" };
    expect(helperChatModelId(chat, models)).toBe("b");
    expect(helperChatModelId({ ...chat, completion_model_id: "gone" }, models)).toBe("a");
    expect(helperChatModelId({ ...chat, completion_model_id: null }, models)).toBe("a");
  });
});

describe("HelperChatSettings", () => {
  it("keeps the pickers behind one button in the narrow panel", async () => {
    const { container } = renderControls();
    const trigger = screen.getByRole("button", { name: "Chattinställningar" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    await expectNoAxeViolations(container);

    await openSettings();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Gäller bara den här chatten.")).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("lists the space's models that use tools, with the default first and marked", async () => {
    renderControls();
    await openSettings();
    const picker = screen.getByRole("button", {
      name: "Chattmodell Standardmodell (standard)"
    });

    fireEvent.click(picker);
    const options = await screen.findAllByRole("option");
    expect(options).toHaveLength(3);
    expect(options[0]!.textContent).toContain("Använd standard");
    expect(options[0]!.textContent).toContain("Standardmodell");
    expect(screen.getByRole("option", { name: /Stark modell/ })).toBeTruthy();
    expect(screen.getByRole("option", { name: /^Standardmodell/ }).textContent).toContain(
      "Standard ·"
    );
    expect(screen.queryByRole("option", { name: /Utan verktyg/ })).toBeNull();
  });

  it("saves a chosen model through the chat, says so and keeps the answer", async () => {
    state.reply = ok({ ...CHAT, completion_model_id: "model-strong" });
    const { queryClient } = renderControls();
    await openSettings();
    fireEvent.click(screen.getByRole("button", { name: /^Chattmodell / }));
    fireEvent.click(await screen.findByRole("option", { name: /Stark modell/ }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith("Chatten använder nu Stark modell.")
    );
    // The settings stay open for the next change; only the list closed.
    expect(screen.getByRole("dialog", { name: "Chattinställningar" })).toBeTruthy();
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/flows/{id}/authoring-chat/{session_id}/", {
      params: { path: { id: "flow-1", session_id: "session-1" } },
      body: { completion_model_id: "model-strong" }
    });
    expect(
      queryClient.getQueryData<FlowAuthoringChat>(flowKeys.authoringChat("flow-1"))
        ?.completion_model_id
    ).toBe("model-strong");
  });

  it("returns to the default with null", async () => {
    state.reply = ok(CHAT);
    renderControls({ ...CHAT, completion_model_id: "model-strong" });
    await openSettings();
    fireEvent.click(screen.getByRole("button", { name: "Chattmodell Stark modell" }));
    fireEvent.click(await screen.findByRole("option", { name: /^Använd standard/ }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(
        "Chatten följer nu standardmodellen Standardmodell."
      )
    );
    expect(api.PATCH).toHaveBeenCalledWith(expect.any(String), {
      params: expect.anything(),
      body: { completion_model_id: null }
    });
  });

  it("hands a refusal to the page and shows the model in force again", async () => {
    state.reply = refused(400, {
      message: "The model's security classification is below the space's.",
      code: "flow_authoring_model_below_classification"
    });
    const { onRefused } = renderControls();
    await openSettings();
    fireEvent.click(screen.getByRole("button", { name: /^Chattmodell / }));
    fireEvent.click(await screen.findByRole("option", { name: /Stark modell/ }));

    await waitFor(() => expect(onRefused).toHaveBeenCalledTimes(1));
    const [error, title] = onRefused.mock.calls[0]!;
    expect(title).toBe("Modellen ändrades inte");
    expect((error as { reason?: string }).reason).toBe("flow_authoring_model_below_classification");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Chattmodell Standardmodell (standard)" })
      ).toBeTruthy()
    );
    expect(state.announce).not.toHaveBeenCalled();
  });

  it("offers the reasoning levels of the model in force, and the model's own default", async () => {
    state.reply = ok({ ...CHAT, completion_model_id: "model-strong", reasoning_effort: "high" });
    renderControls({ ...CHAT, completion_model_id: "model-strong" });
    await openSettings();
    const reasoning = screen.getByRole("combobox", { name: "Resonemangsnivå: Standard" });
    fireEvent.click(reasoning);
    const levels = await screen.findByRole("option", { name: /^Hög/ });
    const listbox = levels.closest<HTMLElement>("[role=listbox]")!;
    expect(within(listbox).getAllByRole("option")[0]!.textContent).toContain("Modellens standard");
    fireEvent.click(levels);

    await waitFor(() => expect(state.announce).toHaveBeenCalledWith("Resonemangsnivån är nu Hög."));
    expect(api.PATCH).toHaveBeenCalledWith(expect.any(String), {
      params: expect.anything(),
      body: { reasoning_effort: "high" }
    });
  });

  it("offers no reasoning level for a model without them", async () => {
    renderControls();
    await openSettings();
    expect(screen.getByRole("button", { name: /^Chattmodell / })).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: /^Resonemangsnivå/ })).toBeNull();
  });
});

describe("NewConversationButton", () => {
  it("starts a new conversation after a confirmation and switches to it", async () => {
    state.reply = ok({ ...CHAT, session_id: "session-2" });
    const { queryClient } = renderControls();
    fireEvent.click(screen.getByRole("button", { name: "Ny konversation" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Starta en ny konversation?" });
    await expectNoAxeViolations(document.body);
    expect(api.POST).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Starta ny konversation" }));

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith("En ny konversation har startat.")
    );
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/flows/{id}/authoring-chat/{session_id}/conversations/",
      { params: { path: { id: "flow-1", session_id: "session-1" } } }
    );
    expect(
      queryClient.getQueryData<FlowAuthoringChat>(flowKeys.authoringChat("flow-1"))?.session_id
    ).toBe("session-2");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("starts nothing when the person cancels", async () => {
    renderControls();
    fireEvent.click(screen.getByRole("button", { name: "Ny konversation" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("ConversationHistoryMenu", () => {
  const conversation = (session: string, title: string, lastAsked: string, current = false) => ({
    session_id: session,
    title,
    started_at: "2026-11-18T08:00:00Z",
    last_asked_at: lastAsked,
    current
  });

  function renderMenu(reply: Reply) {
    api.GET.mockResolvedValue(reply);
    const onPick = vi.fn();
    const chatApi = flowHelperApi(CHAT.flow_id);
    const view = renderInApp(
      <ConversationHistoryMenu
        chat={CHAT}
        api={chatApi}
        list={chatApi.listConversations!}
        onPick={onPick}
      />
    );
    return { ...view, onPick };
  }

  const openMenu = () =>
    fireEvent.click(screen.getByRole("button", { name: messages.helper_history }));

  it("is a named button that opens a menu, and reads the list only once it opens", async () => {
    const { container } = renderMenu(ok({ items: [], count: 0 }));
    const trigger = screen.getByRole("button", { name: messages.helper_history });

    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
    await expectNoAxeViolations(container);
    expect(api.GET).not.toHaveBeenCalled();
    openMenu();
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith("/api/v1/flows/{id}/authoring-chat/conversations/", {
        params: { path: { id: "flow-1" } }
      })
    );
  });

  it("lists the earlier conversations, latest first, by plain name and when last active", async () => {
    const { onPick } = renderMenu(
      ok({
        items: [
          conversation("session-1", "Den aktuella", "2026-11-19T10:00:00Z", true),
          conversation(
            "session-0",
            "Hjälp mig med @[Steg 1](step:abc) och @[Modell](setting:completion_model)",
            "2026-11-18T09:05:00Z"
          ),
          conversation("session-old", "En äldre fråga", "2026-10-02T12:00:00Z")
        ],
        count: 3
      })
    );
    openMenu();

    await screen.findByRole("menuitem", { name: /En äldre fråga/ });
    const items = screen.getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("Hjälp mig med Steg 1 och Modell"),
      expect.stringContaining("En äldre fråga")
    ]);
    expect(items[0]!.textContent).toContain("2026");
    expect(screen.queryByText("Den aktuella")).toBeNull();
    fireEvent.click(items[1]!);
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ session_id: "session-old" }));
  });

  it("says so when there is no earlier conversation", async () => {
    renderMenu(
      ok({ items: [conversation("session-1", "Den aktuella", "2026-11-19T10:00:00Z", true)] })
    );
    openMenu();

    const empty = await screen.findByRole("menuitem", { name: messages.helper_history_empty });
    expect(empty.getAttribute("aria-disabled")).toBe("true");
  });

  it("says when the list could not be read, and reads it again on request", async () => {
    renderMenu(refused(500, { message: "Boom." }));
    openMenu();

    expect(
      await screen.findByRole("menuitem", { name: messages.helper_history_failed })
    ).toBeTruthy();
    api.GET.mockResolvedValue(
      ok({ items: [conversation("session-0", "Andra försöket", "2026-11-18T09:05:00Z")] })
    );
    fireEvent.click(screen.getByRole("menuitem", { name: messages.retry }));

    expect(await screen.findByRole("menuitem", { name: /Andra försöket/ })).toBeTruthy();
    expect(screen.queryByText("Boom.")).toBeNull();
  });
});
