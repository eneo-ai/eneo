import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import type {
  ChatTurnDiagnostics,
  Conversation,
  ConversationMessage,
  Eneo,
  components
} from "@eneo/eneo-js";
import { ChatService, type ChatPartner } from "../../ChatService.svelte";
import ChatDebugPanelFixture from "./ChatDebugPanelFixture.svelte";

type SkillActivationEvidence = components["schemas"]["SkillActivationEvidenceV1"];

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => (resolve = resolvePromise));
  return { promise, resolve };
}

function controlledAsk(messageId: string) {
  let finishStream!: () => void;
  const ask = vi.fn().mockImplementation(
    ({ callbacks }) =>
      new Promise<void>((resolve) => {
        callbacks.onFirstChunk({
          id: messageId,
          session_id: "session-1",
          answer: "",
          references: []
        });
        finishStream = resolve;
      })
  );
  return { ask, finishStream: () => finishStream() };
}

function delayedFirstChunk(messageId: string) {
  let emitFirstChunk!: () => void;
  let finishStream!: () => void;
  const ask = vi.fn().mockImplementation(
    ({ callbacks }) =>
      new Promise<void>((resolve) => {
        emitFirstChunk = () =>
          callbacks.onFirstChunk({
            id: messageId,
            session_id: "session-1",
            answer: "",
            references: []
          });
        finishStream = resolve;
      })
  );
  return {
    ask,
    emitFirstChunk: () => emitFirstChunk(),
    finishStream: () => finishStream()
  };
}

function message(id: string, question: string, extra: Partial<ConversationMessage> = {}) {
  return {
    id,
    question,
    answer: "SENSITIVE_ANSWER",
    reasoning: "SENSITIVE_REASONING",
    completion_model: null,
    references: [],
    files: [],
    generated_files: [],
    web_search_references: [],
    mcp_tool_references: [],
    tool_calls: [],
    tools: { assistants: [] },
    ...extra
  } as ConversationMessage;
}

function createChat(
  getTurnDiagnostics: ReturnType<typeof vi.fn>,
  messages: ConversationMessage[] = [message("message-1", "First question")],
  overrides: {
    ask?: ReturnType<typeof vi.fn>;
    get?: ReturnType<typeof vi.fn>;
  } = {}
) {
  const partner = {
    id: "assistant-1",
    type: "assistant",
    name: "Assistant",
    completion_model: null,
    effective_config: null,
    tools: { assistants: [] },
    attachments: []
  } as unknown as ChatPartner;
  const eneo = {
    conversations: {
      getTurnDiagnostics,
      preflight: vi.fn(),
      ask: overrides.ask ?? vi.fn(),
      get: overrides.get ?? vi.fn(),
      list: vi.fn().mockResolvedValue({
        items: [],
        count: 0,
        total_count: 0,
        next_cursor: null
      })
    }
  } as unknown as Eneo;

  return new ChatService({
    eneo,
    chatPartner: partner,
    initialConversation: { id: "session-1", name: "Conversation", messages },
    initialHistory: { items: [], count: 0, total_count: 0, next_cursor: null }
  });
}

function diagnostics(messageId: string, skillActivation: SkillActivationEvidence | null = null) {
  return {
    session_id: "session-1",
    message_id: messageId,
    skill_activation: skillActivation
  } as ChatTurnDiagnostics;
}

function evidence(count: number): SkillActivationEvidence {
  return {
    version: 1,
    effective_mode: "selective",
    fallback_reason: null,
    available: Array.from({ length: count }, (_, index) => ({
      activation_key: `activation-${index}`,
      skill_id: `skill-${index}-${"x".repeat(72)}`,
      skill_revision_id: `revision-${index}-${"y".repeat(72)}`,
      revision_number: index + 1,
      content_digest: `${index}`.padStart(64, "0"),
      position: index,
      source: "space" as const
    })),
    blocked: [],
    initially_active: [],
    accepted: [],
    repeated: [],
    rejected: [],
    selected_model_id: "model-1",
    selected_model_route: "provider/model",
    skill_context_tokens: 100,
    skill_context_token_limit: 2_000,
    token_count_source: "litellm",
    activation_rounds: 1,
    selection_latency_ms: 12
  };
}

describe("ChatDebugPanel", () => {
  beforeEach(async () => {
    // Desktop by default: the panel renders as an inline resizable sidebar.
    await page.viewport(1280, 800);
    localStorage.clear();
  });

  test("stays hidden when diagnostics are unavailable", async () => {
    const chat = createChat(vi.fn());
    render(ChatDebugPanelFixture, { chat, available: false });

    await expect
      .element(page.getByRole("button", { name: m.chat_debug_open(), exact: true }))
      .not.toBeInTheDocument();
  });

  test("opens as an inline resizable sidebar next to the conversation", async () => {
    const getTurnDiagnostics = vi.fn().mockResolvedValue(diagnostics("message-1", evidence(1)));
    const chat = createChat(getTurnDiagnostics);
    render(ChatDebugPanelFixture, { chat, available: true });

    const trigger = page.getByRole("button", { name: m.chat_debug_open(), exact: true });
    await expect.element(trigger).toHaveAttribute("aria-expanded", "false");
    await trigger.click();

    const sidebar = page.getByRole("complementary", { name: m.chat_debug_title() });
    await expect.element(sidebar).toBeVisible();
    await expect.element(trigger).toHaveAttribute("aria-expanded", "true");
    // The conversation stays visible beside the panel instead of being covered.
    await expect.element(page.getByText("conversation")).toBeVisible();
    // Presence only: component tests run without the app stylesheet, so the
    // 4px-wide handle fails visibility heuristics despite rendering.
    await expect
      .element(page.getByRole("separator", { name: m.chat_debug_resize_handle() }))
      .toBeInTheDocument();
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
  });

  test("falls back to a sheet below the desktop breakpoint", async () => {
    await page.viewport(800, 900);
    const getTurnDiagnostics = vi.fn().mockResolvedValue(diagnostics("message-1", evidence(1)));
    const chat = createChat(getTurnDiagnostics);
    render(ChatDebugPanelFixture, { chat, available: true });

    await page.getByRole("button", { name: m.chat_debug_open(), exact: true }).click();
    await expect.element(page.getByRole("dialog")).toBeVisible();
    await expect
      .element(page.getByRole("separator", { name: m.chat_debug_resize_handle() }))
      .not.toBeInTheDocument();
  });

  test("stays open while the first turn receives its persisted conversation id", async () => {
    const stream = controlledAsk("message-1");
    const getTurnDiagnostics = vi.fn().mockResolvedValue(diagnostics("message-1", evidence(1)));
    const chat = createChat(getTurnDiagnostics, [], { ask: stream.ask });
    chat.newConversation();
    render(ChatDebugPanelFixture, { chat, available: true });

    const trigger = page.getByRole("button", { name: m.chat_debug_open(), exact: true });
    await trigger.click();
    const request = chat.askQuestion("First question");

    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toEqual(["message-1"]));
    await expect
      .element(page.getByRole("complementary", { name: m.chat_debug_title() }))
      .toBeVisible();
    await expect.element(trigger).toHaveAttribute("aria-expanded", "true");
    await vi.waitFor(() =>
      expect(document.querySelector('p[role="status"]')?.textContent).toContain(
        m.chat_debug_live_turn_title()
      )
    );

    stream.finishStream();
    await request;

    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toEqual([]));
    await expect
      .element(page.getByText(m.chat_debug_turn_option({ number: "1" }), { exact: false }).first())
      .toBeVisible();
    await expect.element(page.getByText("provider/model", { exact: true }).first()).toBeVisible();
  });

  test("closes when starting or loading a different conversation", async () => {
    const stream = delayedFirstChunk("stale-message");
    const getTurnDiagnostics = vi.fn().mockResolvedValue(diagnostics("message-1", evidence(1)));
    const get = vi.fn().mockResolvedValue({
      id: "session-2",
      name: "Other conversation",
      messages: [message("message-2", "Other question")]
    });
    const chat = createChat(getTurnDiagnostics, undefined, {
      ask: stream.ask,
      get
    });
    render(ChatDebugPanelFixture, { chat, available: true });

    const trigger = page.getByRole("button", { name: m.chat_debug_open(), exact: true });
    await trigger.click();
    chat.newConversation();
    await expect
      .element(page.getByRole("complementary", { name: m.chat_debug_title() }))
      .not.toBeInTheDocument();
    await expect.element(trigger).toHaveAttribute("aria-expanded", "false");

    await trigger.click();
    const request = chat.askQuestion("Pending question");
    await vi.waitFor(() => expect(chat.askQuestion.isLoading).toBe(true));
    await chat.loadConversation({ id: "session-2" });
    await expect
      .element(page.getByRole("complementary", { name: m.chat_debug_title() }))
      .not.toBeInTheDocument();
    await expect.element(trigger).toHaveAttribute("aria-expanded", "false");
    stream.emitFirstChunk();
    expect(chat.currentConversation.id).toBe("session-2");
    expect(chat.currentConversation.messages.map((item) => item.id)).toEqual(["message-2"]);

    stream.finishStream();
    await request;
  });

  test("closes before an asynchronous assistant context replacement settles", async () => {
    const initialConversation = deferred<Conversation | null>();
    const getTurnDiagnostics = vi.fn().mockResolvedValue(diagnostics("message-1", evidence(1)));
    const chat = createChat(getTurnDiagnostics);
    render(ChatDebugPanelFixture, { chat, available: true });

    const trigger = page.getByRole("button", { name: m.chat_debug_open(), exact: true });
    await trigger.click();
    chat.init({
      eneo: {} as Eneo,
      chatPartner: { ...chat.partner, id: "assistant-2" } as ChatPartner,
      initialConversation: initialConversation.promise,
      initialHistory: { items: [], count: 0, total_count: 0, next_cursor: null }
    });

    await expect
      .element(page.getByRole("complementary", { name: m.chat_debug_title() }))
      .not.toBeInTheDocument();
    await expect.element(trigger).toHaveAttribute("aria-expanded", "false");

    initialConversation.resolve(null);
    await vi.waitFor(() => expect(chat.currentConversation.id).toBe(""));
  });

  test("selects the latest persisted turn and ignores a stale request after partner change", async () => {
    const firstRequest = deferred<ChatTurnDiagnostics>();
    const getTurnDiagnostics = vi.fn().mockReturnValue(firstRequest.promise);
    const chat = createChat(getTurnDiagnostics, [
      message("message-1", "First question"),
      message("message-2", "Latest question")
    ]);
    render(ChatDebugPanelFixture, { chat, available: true });

    await page.getByRole("button", { name: m.chat_debug_open(), exact: true }).click();
    await vi.waitFor(() =>
      expect(getTurnDiagnostics).toHaveBeenCalledWith({
        sessionId: "session-1",
        messageId: "message-2"
      })
    );

    chat.changeChatPartner({ ...chat.partner, id: "assistant-2" } as ChatPartner);
    await expect
      .element(page.getByRole("complementary", { name: m.chat_debug_title() }))
      .not.toBeInTheDocument();

    firstRequest.resolve(diagnostics("message-2", evidence(1)));
    await expect.element(page.getByText("skill-0-" + "x".repeat(72))).not.toBeInTheDocument();
  });

  test("keeps safe MCP metadata while sensitive turn bodies stay out of the DOM", async () => {
    const getTurnDiagnostics = vi
      .fn()
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValue(diagnostics("message-1"));
    const chat = createChat(getTurnDiagnostics, [
      message("message-1", "SENSITIVE_QUESTION", {
        tool_calls: [
          {
            server_name: "calendar",
            tool_name: "list_events",
            result_status: "complete",
            arguments: { secret: "SENSITIVE_ARGUMENT" },
            result: "SENSITIVE_RESULT"
          }
        ],
        mcp_tool_references: [
          {
            id: "reference-1",
            uri: "SENSITIVE_URI",
            content: "SENSITIVE_CONTENT",
            meta: { title: "SENSITIVE_TITLE", incident_reason: "SENSITIVE_INCIDENT" }
          }
        ]
      })
    ]);
    render(ChatDebugPanelFixture, { chat, available: true });

    const trigger = page.getByRole("button", { name: m.chat_debug_open(), exact: true });
    await trigger.click();
    await expect
      .element(page.getByRole("alert").getByText(m.chat_debug_unavailable_title()))
      .toBeVisible();
    await page.getByRole("button", { name: m.chat_debug_retry() }).click();

    await expect.element(page.getByText("list_events")).toBeVisible();
    await expect.element(page.getByText(/· MCP$/)).toBeVisible();
    expect(document.body.textContent).not.toMatch(
      /SENSITIVE_(QUESTION|ANSWER|REASONING|ARGUMENT|RESULT|CONTENT|INCIDENT|TITLE|URI)/
    );

    await userEvent.keyboard("{Escape}");
    await expect
      .element(page.getByRole("complementary", { name: m.chat_debug_title() }))
      .not.toBeInTheDocument();
    await expect.element(trigger).toHaveFocus();
  });

  test("retries diagnostics after a completed turn cannot be confirmed", async () => {
    let finishStream!: () => void;
    const ask = vi.fn().mockImplementation(
      ({ callbacks }) =>
        new Promise<void>((resolve) => {
          callbacks.onFirstChunk({
            id: "message-2",
            session_id: "session-1",
            answer: "",
            references: []
          });
          finishStream = resolve;
        })
    );
    const get = vi.fn();
    let message2Attempts = 0;
    const getTurnDiagnostics = vi.fn(
      ({ messageId }: { messageId: string }): Promise<ChatTurnDiagnostics> => {
        if (messageId === "message-2" && message2Attempts++ === 0) {
          return Promise.reject(new Error("temporary"));
        }
        return Promise.resolve(
          diagnostics(messageId, messageId === "message-2" ? evidence(1) : null)
        );
      }
    );
    const chat = createChat(getTurnDiagnostics, [message("message-1", "First question")], {
      ask,
      get
    });
    render(ChatDebugPanelFixture, { chat, available: true });

    await page.getByRole("button", { name: m.chat_debug_open(), exact: true }).click();
    const request = chat.askQuestion("Latest question");
    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toEqual(["message-2"]));
    finishStream();
    await request;

    await expect
      .element(page.getByRole("alert").getByText(m.chat_debug_confirmation_error_title()))
      .toBeVisible();
    expect(document.querySelector('p[role="status"]')?.textContent).toBe("");
    await page.getByRole("button", { name: m.chat_debug_retry() }).click();

    await vi.waitFor(() => expect(message2Attempts).toBeGreaterThanOrEqual(2));
    expect(chat.pendingDiagnosticsMessageIds).toEqual([]);
    expect(get).not.toHaveBeenCalled();
    await expect.element(page.getByText(m.chat_debug_live_turn_title())).not.toBeInTheDocument();
    await expect.element(page.getByText("provider/model", { exact: true }).first()).toBeVisible();
    await expect
      .element(page.getByText(m.chat_debug_unknown(), { exact: true }))
      .not.toBeInTheDocument();
  });

  test("resizes with the keyboard and restores the saved split on reopen", async () => {
    const getTurnDiagnostics = vi.fn().mockResolvedValue(diagnostics("message-1", evidence(1)));
    const chat = createChat(getTurnDiagnostics);
    render(ChatDebugPanelFixture, { chat, available: true });

    await page.getByRole("button", { name: m.chat_debug_open(), exact: true }).click();
    const handle = page.getByRole("separator", { name: m.chat_debug_resize_handle() });
    await expect.element(handle).toBeInTheDocument();
    const before = Number(handle.element().getAttribute("aria-valuenow"));

    (handle.element() as HTMLElement).focus();
    await userEvent.keyboard("{ArrowLeft}");
    await vi.waitFor(() =>
      expect(Number(handle.element().getAttribute("aria-valuenow"))).not.toBe(before)
    );
    const resized = Number(handle.element().getAttribute("aria-valuenow"));

    // paneforge debounces the autoSaveId write; wait for it before unmounting.
    await vi.waitFor(() => {
      const raw = localStorage.getItem("paneforge:chat-debug-layout");
      expect(raw).toBeTruthy();
      const layouts = Object.values(JSON.parse(raw!)) as { layout: number[] }[];
      expect(
        layouts.some(
          (entry) => entry.layout.length === 2 && Math.round(entry.layout[0]) === resized
        )
      ).toBe(true);
    });

    await page.getByRole("button", { name: m.close(), exact: true }).click();
    await expect
      .element(page.getByRole("complementary", { name: m.chat_debug_title() }))
      .not.toBeInTheDocument();

    await page.getByRole("button", { name: m.chat_debug_open(), exact: true }).click();
    await vi.waitFor(() =>
      expect(
        Number(
          page
            .getByRole("separator", { name: m.chat_debug_resize_handle() })
            .element()
            .getAttribute("aria-valuenow")
        )
      ).toBe(resized)
    );
  });

  test("keeps the selection across breakpoint changes and scopes Escape to the panel", async () => {
    const getTurnDiagnostics = vi.fn(({ messageId }: { messageId: string }) =>
      Promise.resolve(diagnostics(messageId, evidence(1)))
    );
    const chat = createChat(getTurnDiagnostics, [
      message("message-1", "First question", { created_at: "2026-07-27T08:30:00Z" }),
      message("message-2", "Latest question")
    ]);
    render(ChatDebugPanelFixture, { chat, available: true });

    const trigger = page.getByRole("button", { name: m.chat_debug_open(), exact: true });
    await trigger.click();
    await page.getByRole("button", { name: m.chat_debug_previous_turn() }).click();
    await expect.element(page.getByText(m.chat_debug_sent_at(), { exact: true })).toBeVisible();

    // Escape while typing in the composer must not close the panel.
    (page.getByRole("textbox", { name: "composer" }).element() as HTMLElement).focus();
    await userEvent.keyboard("{Escape}");
    await expect
      .element(page.getByRole("complementary", { name: m.chat_debug_title() }))
      .toBeVisible();

    // Crossing the breakpoint swaps the shell but keeps the selected turn.
    await page.viewport(800, 900);
    await expect.element(page.getByRole("dialog")).toBeVisible();
    await expect
      .element(page.getByText(m.chat_debug_turn_option({ number: "1" }), { exact: false }).first())
      .toBeVisible();

    await page.viewport(1280, 800);
    await expect
      .element(page.getByRole("complementary", { name: m.chat_debug_title() }))
      .toBeVisible();
    const callsForSelected = getTurnDiagnostics.mock.calls.filter(
      ([args]) => (args as { messageId: string }).messageId === "message-1"
    );
    expect(callsForSelected).toHaveLength(1);

    // Escape with focus inside the panel closes it and returns focus.
    (page.getByRole("button", { name: m.close(), exact: true }).element() as HTMLElement).focus();
    await userEvent.keyboard("{Escape}");
    await expect
      .element(page.getByRole("complementary", { name: m.chat_debug_title() }))
      .not.toBeInTheDocument();
    await expect.element(trigger).toHaveFocus();
  });

  test("steps between persisted turns with the previous and next buttons", async () => {
    const getTurnDiagnostics = vi.fn(({ messageId }: { messageId: string }) =>
      Promise.resolve(diagnostics(messageId, evidence(1)))
    );
    const chat = createChat(getTurnDiagnostics, [
      message("message-1", "First question"),
      message("message-2", "Latest question")
    ]);
    render(ChatDebugPanelFixture, { chat, available: true });

    await page.getByRole("button", { name: m.chat_debug_open(), exact: true }).click();
    const previous = page.getByRole("button", { name: m.chat_debug_previous_turn() });
    const next = page.getByRole("button", { name: m.chat_debug_next_turn() });
    await expect.element(next).toBeDisabled();

    await previous.click();
    await vi.waitFor(() =>
      expect(getTurnDiagnostics).toHaveBeenCalledWith({
        sessionId: "session-1",
        messageId: "message-1"
      })
    );
    await expect.element(previous).toBeDisabled();
    await expect.element(next).not.toBeDisabled();
  });

  test("preserves an explicit turn selection when a newer turn becomes available", async () => {
    const stream = controlledAsk("message-3");
    const getTurnDiagnostics = vi.fn(({ messageId }: { messageId: string }) =>
      Promise.resolve(diagnostics(messageId, evidence(1)))
    );
    const chat = createChat(
      getTurnDiagnostics,
      [message("message-1", "First question"), message("message-2", "Second question")],
      { ask: stream.ask }
    );
    render(ChatDebugPanelFixture, { chat, available: true });

    await page.getByRole("button", { name: m.chat_debug_open(), exact: true }).click();
    await page.getByRole("button", { name: m.chat_debug_previous_turn() }).click();
    const firstTurnLabel = page
      .getByText(m.chat_debug_turn_option({ number: "1" }), { exact: false })
      .first();
    await expect.element(firstTurnLabel).toBeVisible();

    const request = chat.askQuestion("Third question");
    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toEqual(["message-3"]));
    stream.finishStream();
    await request;

    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toEqual([]));
    await expect.element(firstTurnLabel).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.chat_debug_next_turn() }))
      .not.toBeDisabled();
  });

  test("resumes following new turns after returning to the latest turn", async () => {
    const stream = controlledAsk("message-3");
    const getTurnDiagnostics = vi.fn(({ messageId }: { messageId: string }) =>
      Promise.resolve(diagnostics(messageId, evidence(1)))
    );
    const chat = createChat(
      getTurnDiagnostics,
      [message("message-1", "First question"), message("message-2", "Second question")],
      { ask: stream.ask }
    );
    render(ChatDebugPanelFixture, { chat, available: true });

    await page.getByRole("button", { name: m.chat_debug_open(), exact: true }).click();
    await page.getByRole("button", { name: m.chat_debug_previous_turn() }).click();
    await page.getByRole("button", { name: m.chat_debug_next_turn() }).click();

    const request = chat.askQuestion("Third question");
    await vi.waitFor(() => expect(chat.pendingDiagnosticsMessageIds).toEqual(["message-3"]));
    stream.finishStream();
    await request;

    await vi.waitFor(() =>
      expect(getTurnDiagnostics).toHaveBeenCalledWith({
        sessionId: "session-1",
        messageId: "message-3"
      })
    );
    await expect
      .element(page.getByText(m.chat_debug_turn_option({ number: "3" }), { exact: false }).first())
      .toBeVisible();
  });

  test("distinguishes legacy evidence from zero candidates and reveals large lists in chunks", async () => {
    const getTurnDiagnostics = vi
      .fn()
      .mockResolvedValueOnce(diagnostics("message-1"))
      .mockResolvedValueOnce(diagnostics("message-1", evidence(0)))
      .mockResolvedValueOnce(diagnostics("message-1", evidence(1_000)));
    const chat = createChat(getTurnDiagnostics);
    render(ChatDebugPanelFixture, { chat, available: true });

    await page.getByRole("button", { name: m.chat_debug_open(), exact: true }).click();
    await expect.element(page.getByText(m.chat_debug_legacy_skills_title())).toBeVisible();
    await page.getByRole("button", { name: m.chat_debug_refresh() }).click();
    await expect.element(page.getByText(m.chat_debug_zero_skills_title())).toBeVisible();
    await page.getByRole("button", { name: m.chat_debug_refresh() }).click();

    const firstSkill = "skill-0-" + "x".repeat(72);
    const fiftyFirstSkill = "skill-50-" + "x".repeat(72);
    await expect.element(page.getByText(firstSkill)).toBeVisible();
    await expect.element(page.getByText(fiftyFirstSkill)).not.toBeInTheDocument();
    await page.getByRole("button", { name: m.chat_debug_show_more({ count: "50" }) }).click();
    await expect.element(page.getByText(fiftyFirstSkill)).toBeVisible();
  });
});
