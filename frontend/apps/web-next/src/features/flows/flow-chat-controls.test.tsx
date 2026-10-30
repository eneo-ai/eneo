// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import {
  FlowChatSettings,
  NewConversationButton,
  OptimizeFlowButton,
  flowChatModelId
} from "./flow-chat-controls";
import { flowKeys, type FlowAuthoringChat } from "./flows-api";

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
  const view = renderInApp(
    <div>
      <FlowChatSettings chat={chat} onRefused={onRefused} />
      <NewConversationButton chat={chat} onRefused={onRefused} />
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

describe("flowChatModelId", () => {
  const models = [model("a", "A"), model("b", "B")] as never[];

  it("is the person's own model while the space offers it, else the default", () => {
    const chat = { completion_model_id: "b", default_completion_model_id: "a" };
    expect(flowChatModelId(chat, models)).toBe("b");
    expect(flowChatModelId({ ...chat, completion_model_id: "gone" }, models)).toBe("a");
    expect(flowChatModelId({ ...chat, completion_model_id: null }, models)).toBe("a");
  });
});

describe("FlowChatSettings", () => {
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
      name: "Chattmodell: Standardmodell (standard)"
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
    fireEvent.click(screen.getByRole("button", { name: /^Chattmodell: / }));
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
    fireEvent.click(screen.getByRole("button", { name: "Chattmodell: Stark modell" }));
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
    fireEvent.click(screen.getByRole("button", { name: /^Chattmodell: / }));
    fireEvent.click(await screen.findByRole("option", { name: /Stark modell/ }));

    await waitFor(() => expect(onRefused).toHaveBeenCalledTimes(1));
    const [error, title] = onRefused.mock.calls[0]!;
    expect(title).toBe("Modellen ändrades inte");
    expect((error as { reason?: string }).reason).toBe("flow_authoring_model_below_classification");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Chattmodell: Standardmodell (standard)" })
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
    expect(screen.getByRole("button", { name: /^Chattmodell: / })).toBeTruthy();
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

describe("OptimizeFlowButton", () => {
  it("hands the prepared review request to the composer and sends nothing", async () => {
    const onAskChat = vi.fn();
    const { container } = renderInApp(<OptimizeFlowButton onAskChat={onAskChat} />);

    fireEvent.click(screen.getByRole("button", { name: "Optimera flödet" }));
    expect(onAskChat).toHaveBeenCalledWith(
      expect.stringMatching(/^Gå igenom flödets förslag och visa vad som kan göra det billigare/)
    );
    // The request is the person's own message: it names no tool.
    expect(onAskChat).not.toHaveBeenCalledWith(expect.stringContaining("read_flow_suggestions"));
    expect(api.POST).not.toHaveBeenCalled();
    expect(api.PATCH).not.toHaveBeenCalled();
    await expectNoAxeViolations(container);
  });
});
