/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { browser } from "$app/environment";
import { PAGINATION } from "$lib/core/constants";
import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
import { createClassContext } from "$lib/core/helpers/createClassContext";
import { getIntric } from "$lib/core/Intric";
import { CalendarDate } from "@internationalized/date";
import type { ChatPartner, Conversation, ConversationSparse, Intric } from "@intric/intric-js";

type InsightStatistics = Awaited<
  ReturnType<Intric["analytics"]["insights"]["statistics"]>
>;

class InsightsService {
  #intric: Intric;
  /** General data range for all insight requests */
  dateRange: { start: CalendarDate | undefined; end: CalendarDate | undefined } = $state()!;
  /** Stable date range used for requests, guards against transient undefined bindings */
  #activeDateRange: { start: CalendarDate; end: CalendarDate } = $state()!;
  /** Last chat partner */
  #chatPartner: ChatPartner = $state()!;
  /** Some basic statistics */
  statistics = $state<InsightStatistics | null>(null);
  statisticsLoading = $state(false);
  statisticsError = $state<string | null>(null);
  // Conversation handling
  conversationFilter = $state("");
  conversationListError = $state<string | null>(null);
  #nextCursor = $state<string | undefined>(undefined);
  /** Conversations to explore */
  conversations: ConversationSparse[] = $state([]);
  totalConversationCount = $state(0);
  hasMoreConversations = $derived(Boolean(this.#nextCursor));
  /** Currently previewed conversation */
  previewedConversation = $state<Conversation | null>(null);
  previewLoadError = $state<string | null>(null);
  // Handling to ask some stuff
  question = $state("");
  answer = $state("");
  analysisJobId = $state<string | null>(null);
  analysisJobStatus = $state<"queued" | "processing" | "completed" | "failed" | null>(null);
  analysisJobError = $state<string | null>(null);

  #previewRequestId = 0;
  #analysisPollRequestId = 0;
  #conversationsRequestId = 0;
  #statisticsRequestId = 0;
  #lastStatisticsKey = $state<string | null>(null);
  #lastConversationsKey = $state<string | null>(null);
  #statisticsLoaded = $state(false);
  #conversationsLoaded = $state(false);

  constructor(intric = getIntric(), chatPartner: () => ChatPartner) {
    this.#intric = intric;

    const now = new Date();
    const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getUTCDate());

    const defaultDateRange = {
      start: today.subtract({ days: 30 }),
      end: today
    };

    this.dateRange = defaultDateRange;
    this.#activeDateRange = defaultDateRange;

    $effect(() => {
      const currentPartner = chatPartner();
      if (!currentPartner) {
        return;
      }
      const hasPartnerChanged =
        !this.#chatPartner ||
        this.#chatPartner.id !== currentPartner.id ||
        this.#chatPartner.type !== currentPartner.type;

      this.#chatPartner = currentPartner;

      if (!hasPartnerChanged) {
        return;
      }

      this.#previewRequestId += 1;
      this.#analysisPollRequestId += 1;
      this.#statisticsRequestId += 1;
      this.#conversationsRequestId += 1;
      this.previewedConversation = null;
      this.previewLoadError = null;
      this.answer = "";
      this.question = "";
      this.conversationFilter = "";
      this.conversationListError = null;
      this.analysisJobId = null;
      this.analysisJobStatus = null;
      this.analysisJobError = null;
      this.statistics = null;
      this.statisticsLoading = false;
      this.statisticsError = null;
      this.#statisticsLoaded = false;
      this.#conversationsLoaded = false;
      this.#lastStatisticsKey = null;
      this.#lastConversationsKey = null;
      this.#nextCursor = undefined;
      this.conversations = [];
      this.totalConversationCount = 0;
    });

    $effect(() => {
      const nextStart = this.dateRange.start;
      const nextEnd = this.dateRange.end;

      if (!nextStart || !nextEnd) {
        return;
      }

      this.#activeDateRange = {
        start: nextStart,
        end: nextEnd
      };
    });

    $effect(() => {
      const start = this.#activeDateRange.start?.toString();
      const end = this.#activeDateRange.end?.toString();
      const partnerId = this.#chatPartner?.id;

      if (!partnerId || !start || !end) {
        return;
      }

      const range = {
        start: this.#activeDateRange.start,
        end: this.#activeDateRange.end
      };

      this.#updateStatistics(range);
      this.#updateConversations(range);
    });
  }

  async #updateStatistics(timeframe: {
    start: CalendarDate | undefined;
    end: CalendarDate | undefined;
  }) {
    // Should only run during effect by default, but let's prevent this being called on the server.
    if (!browser) return;
    if (!this.#chatPartner) return;

    if (timeframe.start && timeframe.end) {
      const statisticsKey = [
        this.#chatPartner.type,
        this.#chatPartner.id,
        timeframe.start.toString(),
        timeframe.end.toString()
      ].join("|");
      if (
        this.#statisticsLoaded &&
        this.#lastStatisticsKey === statisticsKey &&
        !this.statisticsError
      ) {
        return;
      }

      this.#lastStatisticsKey = statisticsKey;
      const requestId = ++this.#statisticsRequestId;
      this.statisticsLoading = true;
      this.statisticsError = null;
      try {
        const result = await this.#intric.analytics.insights.statistics({
          chatPartner: this.#chatPartner,
          startDate: timeframe?.start?.toString(),
          // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
          endDate: timeframe?.end?.add({ days: 1 }).toString()
        });

        if (requestId !== this.#statisticsRequestId) {
          return;
        }

        this.statistics = result;
        this.#statisticsLoaded = true;
      } catch (error) {
        if (requestId !== this.#statisticsRequestId) {
          return;
        }
        this.statisticsError = "failed";
        this.#lastStatisticsKey = null;
      } finally {
        if (requestId === this.#statisticsRequestId) {
          this.statisticsLoading = false;
        }
      }
    }
  }

  async #updateConversations(
    timeframe: { start: CalendarDate | undefined; end: CalendarDate | undefined },
    append = false
  ) {
    // Should only run during effect by default, but let's prevent this being called on the server.
    if (!browser) return;

    if (timeframe.start && timeframe.end) {
      if (!this.#chatPartner) {
        return;
      }

      const conversationsKey = [
        this.#chatPartner.type,
        this.#chatPartner.id,
        timeframe.start.toString(),
        timeframe.end.toString(),
        this.conversationFilter.trim()
      ].join("|");

      if (
        !append &&
        this.#conversationsLoaded &&
        this.#lastConversationsKey === conversationsKey &&
        !this.conversationListError
      ) {
        return;
      }

      if (!append) {
        this.#lastConversationsKey = conversationsKey;
      }

      const requestId = ++this.#conversationsRequestId;

      if (!append) {
        this.conversationListError = null;
      }

      try {
        const conversations = await this.#intric.analytics.insights.conversations.list({
          chatPartner: this.#chatPartner,
          startDate: timeframe?.start?.toString(),
          // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
          endDate: timeframe?.end?.add({ days: 1 }).toString(),
          nextCursor: append ? this.#nextCursor : undefined,
          limit: PAGINATION.PAGE_SIZE,
          nameFilter: this.conversationFilter || undefined
        });

        if (requestId !== this.#conversationsRequestId) {
          return;
        }

        if (append) {
          const seen = new Set(this.conversations.map((conversation) => conversation.id));
          const merged = [...this.conversations];
          for (const conversation of conversations.items) {
            if (!seen.has(conversation.id)) {
              merged.push(conversation);
              seen.add(conversation.id);
            }
          }
          this.conversations = merged;
        } else {
          this.conversations = conversations.items;
        }

        this.#nextCursor = conversations.next_cursor ?? undefined;
        this.totalConversationCount = conversations.total_count;
        this.#conversationsLoaded = true;
      } catch (error) {
        if (requestId !== this.#conversationsRequestId) {
          return;
        }
        this.conversationListError = "failed";
        if (!append) {
          this.#lastConversationsKey = null;
        }
        if (!append) {
          this.conversations = [];
          this.totalConversationCount = 0;
          this.#nextCursor = undefined;
        }
      }
    }
  }

  loadMoreConversations = createAsyncState(async () => {
    if (!this.#nextCursor) {
      return;
    }
    await this.#updateConversations(this.#activeDateRange, true);
  });

  searchConversations = createAsyncState(async (nameFilter: string) => {
    const normalized = nameFilter.trim();
    if (normalized === this.conversationFilter.trim()) {
      return;
    }
    this.conversationFilter = normalized;
    this.#nextCursor = undefined;
    this.previewedConversation = null;
    this.previewLoadError = null;
    await this.#updateConversations(this.#activeDateRange);
  });

  loadConversationPreview = createAsyncState(async (conversation: { id: string }) => {
    this.previewLoadError = null;
    const requestId = ++this.#previewRequestId;
    let loadedConversation;
    try {
      loadedConversation = await this.#intric.analytics.insights.conversations.get(conversation);
    } catch (error) {
      if (requestId === this.#previewRequestId) {
        this.previewLoadError = "failed";
      }
      return;
    }
    if (requestId !== this.#previewRequestId) {
      return;
    }
    this.previewedConversation = loadedConversation;
  });

  askQuestion = createAsyncState(async (question: string) => {
    const requestId = ++this.#analysisPollRequestId;
    this.answer = "";
    this.question = question;
    this.analysisJobId = null;
    this.analysisJobStatus = null;
    this.analysisJobError = null;

    let response;
    try {
      response = await this.#intric.analytics.insights.ask({
        startDate: this.#activeDateRange.start?.toString(),
        // We add one day so the end day includes the whole day. otherwise this would be interpreted as 00:00
        endDate: this.#activeDateRange.end?.add({ days: 1 }).toString(),
        chatPartner: this.#chatPartner,
        question,
        processingMode: "auto",
        onAnswer: (answer) => {
          this.answer += answer;
        }
      });
    } catch (error) {
      this.analysisJobStatus = "failed";
      this.analysisJobError = "failed";
      return;
    }

    if (requestId !== this.#analysisPollRequestId) {
      return;
    }

    if (response?.isAsync && response?.jobId) {
      this.analysisJobId = response.jobId;
      this.analysisJobStatus = response.status ?? "queued";
      await this.#pollAnalysisJob(response.jobId, requestId);
      return;
    }

    this.analysisJobStatus = response?.status ?? "completed";
    this.answer = response.answer;
  });

  async #pollAnalysisJob(jobId: string, requestId: number): Promise<void> {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (requestId !== this.#analysisPollRequestId) {
        return;
      }

      let status;
      try {
        status = await this.#intric.analytics.insights.getJobStatus({ jobId });
      } catch (error) {
        this.analysisJobStatus = "failed";
        this.analysisJobError = "failed";
        return;
      }
      this.analysisJobStatus = status.status ?? "processing";

      if (status.status === "completed") {
        this.answer = status.answer ?? "";
        this.analysisJobError = null;
        return;
      }

      if (status.status === "failed") {
        this.analysisJobError = status.error ?? "Failed to generate insights.";
        return;
      }

      await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    this.analysisJobStatus = "failed";
    this.analysisJobError = "Insights generation timed out. Please try again.";
  }
}

export const [getInsightsService, initInsightsService] = createClassContext(
  "Insights service",
  InsightsService
);
