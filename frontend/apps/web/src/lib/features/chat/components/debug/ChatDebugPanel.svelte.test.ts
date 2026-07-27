import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import type { ChatTurnDiagnostics, ConversationMessage, Eneo, components } from "@eneo/eneo-js";
import { ChatService, type ChatPartner } from "../../ChatService.svelte";
import ChatDebugPanel from "./ChatDebugPanel.svelte";

type SkillActivationEvidence = components["schemas"]["SkillActivationEvidenceV1"];

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => (resolve = resolvePromise));
  return { promise, resolve };
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
  messages: ConversationMessage[] = [message("message-1", "First question")]
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
      ask: vi.fn(),
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
  test("stays hidden when diagnostics are unavailable", async () => {
    const chat = createChat(vi.fn());
    render(ChatDebugPanel, { chat, available: false });

    await expect
      .element(page.getByRole("button", { name: m.chat_debug_open() }))
      .not.toBeInTheDocument();
  });

  test("selects the latest persisted turn and ignores a stale request after partner change", async () => {
    const firstRequest = deferred<ChatTurnDiagnostics>();
    const getTurnDiagnostics = vi.fn().mockReturnValue(firstRequest.promise);
    const chat = createChat(getTurnDiagnostics, [
      message("message-1", "First question"),
      message("message-2", "Latest question")
    ]);
    render(ChatDebugPanel, { chat, available: true });

    const trigger = page.getByRole("button", { name: m.chat_debug_open() });
    await expect.element(trigger).toHaveAttribute("aria-haspopup", "dialog");
    await trigger.click();
    await vi.waitFor(() =>
      expect(getTurnDiagnostics).toHaveBeenCalledWith({
        sessionId: "session-1",
        messageId: "message-2"
      })
    );

    chat.changeChatPartner({ ...chat.partner, id: "assistant-2" } as ChatPartner);
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();

    firstRequest.resolve(diagnostics("message-2", evidence(1)));
    await expect.element(page.getByText("skill-0-" + "x".repeat(72))).not.toBeInTheDocument();
  });

  test("keeps safe MCP metadata while sensitive turn bodies stay out of the DOM", async () => {
    const getTurnDiagnostics = vi
      .fn()
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValue(diagnostics("message-1"));
    const chat = createChat(getTurnDiagnostics, [
      message("message-1", "Inspect metadata", {
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
            uri: "mcp://calendar/events",
            content: "SENSITIVE_CONTENT",
            meta: { title: "Calendar events", incident_reason: "SENSITIVE_INCIDENT" }
          }
        ]
      })
    ]);
    render(ChatDebugPanel, { chat, available: true });

    const trigger = page.getByRole("button", { name: m.chat_debug_open() });
    await trigger.click();
    await expect
      .element(page.getByRole("alert").getByText(m.chat_debug_unavailable_title()))
      .toBeVisible();
    await page.getByRole("button", { name: m.chat_debug_retry() }).click();

    await expect.element(page.getByText("list_events")).toBeVisible();
    await expect.element(page.getByText("Calendar events")).toBeVisible();
    await expect.element(page.getByText("mcp://calendar/events")).toBeVisible();
    expect(document.body.textContent).not.toMatch(
      /SENSITIVE_(ANSWER|REASONING|ARGUMENT|RESULT|CONTENT|INCIDENT)/
    );

    await userEvent.keyboard("{Escape}");
    await expect.element(trigger).toHaveFocus();
  });

  test("distinguishes legacy evidence from zero candidates and reveals large lists in chunks", async () => {
    const getTurnDiagnostics = vi
      .fn()
      .mockResolvedValueOnce(diagnostics("message-1"))
      .mockResolvedValueOnce(diagnostics("message-1", evidence(0)))
      .mockResolvedValueOnce(diagnostics("message-1", evidence(1_000)));
    const chat = createChat(getTurnDiagnostics);
    render(ChatDebugPanel, { chat, available: true });

    await page.getByRole("button", { name: m.chat_debug_open() }).click();
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
