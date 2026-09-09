/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { browser } from "$app/environment";
import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
import { createClassContext } from "$lib/core/helpers/createClassContext";
import type { CalendarDate } from "@internationalized/date";
import type { ChatPartner, ConversationMessage, Eneo } from "@eneo/eneo-js";

export type InsightsToolCall = NonNullable<ConversationMessage["tool_calls"]>[number];

/**
 * One turn of the insights chat: the operator's question and the model's
 * answer as it streams in, plus the tool calls the model made on the way.
 */
export type InsightsChatMessage = {
  id: string | null;
  question: string;
  answer: string;
  reasoning: string;
  toolCalls: InsightsToolCall[];
  /** Terminal error from the stream, if the turn failed. */
  error: string | null;
};

/** A previous analysis, as listed in the history. */
export type InsightsConversationSummary = {
  id: string;
  name: string;
  created_at?: string | null;
};

type DateRange = { start: CalendarDate | undefined; end: CalendarDate | undefined };

type StreamCallbacks = {
  onFirstChunk: (chunk: { id?: string | null; session_id: string }) => void;
  onText: (event: { answer: string }) => void;
  onReasoning: (event: { reasoning: string }) => void;
  onToolCall: (event: {
    tools: Array<{ tool_call_id?: string | null } & InsightsToolCall>;
  }) => void;
  onError: (event: { error: string }) => void;
};

/**
 * State of the insights analysis chat for the current chat partner: the open
 * conversation (new or resumed), and the operator's previous analyses. The
 * model answers by calling Eneo's own insights tools, whose steps stream in
 * as tool calls; follow-ups continue the same persisted conversation.
 */
class InsightsChatService {
  #eneo: Eneo;
  #chatPartner: () => ChatPartner;
  #dateRange: () => DateRange;
  #abortController: AbortController | null = null;
  #streamGeneration = 0;
  #historyRequestId = 0;
  #openRequestId = 0;
  #toolCallResultCache = new Map<string, Promise<string | null>>();

  messages = $state<InsightsChatMessage[]>([]);
  conversationId = $state<string | null>(null);
  isStreaming = $state(false);
  /** Error code of the last failed request, or null. */
  error = $state<string | null>(null);

  history = $state<InsightsConversationSummary[]>([]);
  historyTotal = $state(0);
  historyError = $state<string | null>(null);
  #historyCursor = $state<string | null>(null);
  hasMoreHistory = $derived(this.#historyCursor !== null);

  constructor(eneo: Eneo, chatPartner: () => ChatPartner, dateRange: () => DateRange) {
    this.#eneo = eneo;
    this.#chatPartner = chatPartner;
    this.#dateRange = dateRange;

    let lastPartnerKey: string | null = null;
    $effect(() => {
      const partner = chatPartner();
      const key = partner ? `${partner.type}|${partner.id}` : null;
      if (key === lastPartnerKey) return;
      lastPartnerKey = key;
      this.reset();
      this.#resetHistory();
      if (key) this.loadHistory();
    });
  }

  /** Drop the open conversation, aborting any stream in flight. */
  reset() {
    this.#abortController?.abort();
    this.#abortController = null;
    this.#streamGeneration += 1;
    this.#openRequestId += 1;
    this.messages = [];
    this.conversationId = null;
    this.isStreaming = false;
    this.error = null;
  }

  #resetHistory() {
    this.#historyRequestId += 1;
    this.history = [];
    this.historyTotal = 0;
    this.historyError = null;
    this.#historyCursor = null;
  }

  loadHistory = createAsyncState(async (append = false) => {
    if (!browser) return;
    const partner = this.#chatPartner();
    if (!partner) return;
    const requestId = ++this.#historyRequestId;
    if (!append) this.historyError = null;
    try {
      const page = await this.#eneo.analytics.insights.chat.list({
        chatPartner: partner,
        limit: 20,
        cursor: append ? (this.#historyCursor ?? undefined) : undefined
      });
      if (requestId !== this.#historyRequestId) return;
      const items = page.items as InsightsConversationSummary[];
      this.history = append ? [...this.history, ...items] : items;
      this.historyTotal = page.total_count;
      this.#historyCursor = page.next_cursor ?? null;
    } catch {
      if (requestId !== this.#historyRequestId) return;
      this.historyError = "failed";
    }
  });

  /** Resume a previous analysis with all its turns. */
  openConversation = createAsyncState(async (conversation: { id: string }) => {
    if (!browser) return;
    this.reset();
    const requestId = this.#openRequestId;
    try {
      const session = await this.#eneo.analytics.insights.chat.get(conversation);
      if (requestId !== this.#openRequestId) return;
      this.conversationId = session.id;
      this.messages = session.messages.map((message) => ({
        id: message.id ?? null,
        question: message.question,
        answer: message.answer,
        reasoning: message.reasoning ?? "",
        toolCalls: message.tool_calls ?? [],
        error: null
      }));
    } catch {
      if (requestId !== this.#openRequestId) return;
      this.error = "failed";
    }
  });

  /** Result text of one tool call in the open conversation, cached per call. */
  getToolCallResult(toolCallId: string): Promise<string | null> {
    const conversationId = this.conversationId;
    if (!conversationId) {
      return Promise.resolve(null);
    }
    const cacheKey = `${conversationId}:${toolCallId}`;
    const cached = this.#toolCallResultCache.get(cacheKey);
    if (cached) return cached;
    const request = this.#eneo.analytics.insights.chat
      .getToolCallResult({ conversation: { id: conversationId }, toolCallId })
      .then((response) => response.result ?? null)
      .catch((error) => {
        this.#toolCallResultCache.delete(cacheKey);
        throw error;
      });
    this.#toolCallResultCache.set(cacheKey, request);
    return request;
  }

  deleteConversation = createAsyncState(async (conversation: { id: string }) => {
    try {
      await this.#eneo.analytics.insights.chat.delete(conversation);
    } catch {
      this.historyError = "failed";
      return;
    }
    this.history = this.history.filter((item) => item.id !== conversation.id);
    this.historyTotal = Math.max(0, this.historyTotal - 1);
    if (this.conversationId === conversation.id) this.reset();
  });

  async send(question: string) {
    if (!browser || this.isStreaming) return;
    const trimmed = question.trim();
    if (!trimmed) return;

    const generation = ++this.#streamGeneration;
    const isStale = () => generation !== this.#streamGeneration;
    const abortController = new AbortController();
    this.#abortController = abortController;

    const message: InsightsChatMessage = {
      id: null,
      question: trimmed,
      answer: "",
      reasoning: "",
      toolCalls: [],
      error: null
    };
    this.messages.push(message);
    const ref = this.messages[this.messages.length - 1];
    this.isStreaming = true;
    this.error = null;
    const isNewConversation = this.conversationId === null;

    const range = this.#dateRange();
    const selectedRange =
      range.start && range.end
        ? { start: range.start.toString(), end: range.end.toString() }
        : undefined;

    const callbacks: StreamCallbacks = {
      onFirstChunk: (chunk) => {
        if (isStale()) return;
        ref.id = chunk.id ?? null;
        this.conversationId = chunk.session_id;
      },
      onText: (event) => {
        if (isStale()) return;
        ref.answer += event.answer;
      },
      onReasoning: (event) => {
        if (isStale()) return;
        ref.reasoning += event.reasoning;
      },
      onToolCall: (event) => {
        if (isStale()) return;
        for (const tool of event.tools) {
          const index = ref.toolCalls.findIndex(
            (existing) => existing.tool_call_id && existing.tool_call_id === tool.tool_call_id
          );
          if (index >= 0) {
            ref.toolCalls[index] = { ...ref.toolCalls[index], ...tool };
          } else {
            ref.toolCalls.push(tool);
          }
        }
      },
      onError: (event) => {
        if (isStale()) return;
        ref.error = event.error || "failed";
        this.error = "failed";
      }
    };

    try {
      if (this.conversationId === null) {
        await this.#eneo.analytics.insights.chat.ask({
          chatPartner: this.#chatPartner(),
          question: trimmed,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          selectedRange,
          abortController,
          callbacks
        });
      } else {
        await this.#eneo.analytics.insights.chat.continue({
          conversation: { id: this.conversationId },
          question: trimmed,
          selectedRange,
          abortController,
          callbacks
        });
      }
      // A new conversation now exists on the backend: show it in the history.
      if (isNewConversation && !isStale()) this.loadHistory();
    } catch (error) {
      if (isStale() || abortController.signal.aborted) return;
      const code =
        typeof error === "object" && error !== null && "code" in error
          ? String((error as { code?: unknown }).code ?? "failed")
          : "failed";
      ref.error = code;
      this.error = code;
    } finally {
      if (!isStale()) {
        this.isStreaming = false;
        this.#abortController = null;
      }
    }
  }
}

export const [getInsightsChatService, initInsightsChatService] = createClassContext(
  "Insights chat service",
  InsightsChatService
);
