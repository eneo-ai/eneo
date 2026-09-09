/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { browser } from "$app/environment";
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

type DateRange = { start: CalendarDate | undefined; end: CalendarDate | undefined };

/**
 * State of the insights analysis chat for the current chat partner. Each
 * question starts a new persisted conversation on the backend (multi-turn
 * follow-ups arrive with the history endpoints); the model answers by calling
 * Eneo's own insights tools, whose steps stream in as tool calls.
 */
class InsightsChatService {
  #eneo: Eneo;
  #chatPartner: () => ChatPartner;
  #dateRange: () => DateRange;
  #abortController: AbortController | null = null;
  #streamGeneration = 0;

  messages = $state<InsightsChatMessage[]>([]);
  conversationId = $state<string | null>(null);
  isStreaming = $state(false);
  /** Error code of the last failed request, or null. */
  error = $state<string | null>(null);

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
    });
  }

  /** Drop the current conversation, aborting any stream in flight. */
  reset() {
    this.#abortController?.abort();
    this.#abortController = null;
    this.#streamGeneration += 1;
    this.messages = [];
    this.conversationId = null;
    this.isStreaming = false;
    this.error = null;
  }

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

    const range = this.#dateRange();
    const selectedRange =
      range.start && range.end
        ? { start: range.start.toString(), end: range.end.toString() }
        : undefined;

    try {
      await this.#eneo.analytics.insights.chat.ask({
        chatPartner: this.#chatPartner(),
        question: trimmed,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        selectedRange,
        abortController,
        callbacks: {
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
        }
      });
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
