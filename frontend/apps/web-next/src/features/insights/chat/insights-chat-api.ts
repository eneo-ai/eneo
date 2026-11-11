/**
 * The insights chat's endpoints, under `/api/v1/analysis/conversation-insights/chat`.
 *
 * This module is the one seam between the insights chat and its backend.
 * The generated schema (src/lib/api/schema.d.ts) has none of these paths
 * yet, so the requests are written by hand here, typed with the schema's
 * own models where they exist (SessionPublic, SessionMetadataPublic,
 * ToolCallResultPublic). Once the backend lands and `bun run gen:api` adds
 * the paths, switch the requests to `browserApi` and drop the hand-written
 * request types; nothing outside this module needs to change.
 *
 * A turn streams the same version 3 UI Message Stream as the chat API
 * (src/lib/chat/CONTRACT.md); the transport here only changes where a turn
 * goes and what its body says. An analysis whose conversations have been
 * removed is removed with them: the list leaves it out, and opening or
 * continuing it is refused with 410 `derived_source_removed`
 * (`isDerivedSourceRemoved`).
 */
import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import { API_BASE, apiFetch } from "@/lib/api/base";
import { apiErrorFromResponse } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { cursorPagination } from "@/lib/api/pagination";
import type { IsoDate } from "@/lib/calendar-date";
import { createChatTransport } from "@/lib/chat/transport";
import type { ChatPartner } from "@/lib/chat/types";
import type { ConversationApi } from "@/features/chat/chat-view";
import type { ToolResultSource } from "@/features/chat/tool-results";

const CHAT_PATH = `${API_BASE}/api/v1/analysis/conversation-insights/chat`;

/** Whose conversations are analysed: an assistant or a group chat. */
export type InsightTarget = Pick<ChatPartner, "id"> & { type: "assistant" | "group-chat" };

/** The period picker's range: local calendar dates, both ends included. */
export type InsightSelectedRange = { start: IsoDate; end: IsoDate };

/** `POST /`: starts an analysis of one target's conversations. */
type InsightChatStartRequest = {
  assistant_id?: string;
  group_chat_id?: string;
  question: string;
  /** The browser's IANA time zone: "yesterday" is the operator's yesterday. */
  timezone: string;
  stream: true;
  selected_range?: InsightSelectedRange;
};

/** `POST /{session_id}/`: a follow-up question in an analysis. */
type InsightChatContinueRequest = {
  question: string;
  stream: true;
  selected_range?: InsightSelectedRange;
};

/** A listed analysis: its name is the question it started with. */
export type InsightConversationSummary = Schema<"SessionMetadataPublic">;
export type InsightConversationPage = Schema<"CursorPaginatedResponse_SessionMetadataPublic_">;
/** An analysis with every turn, as `mapSessionMessages` reads it. */
export type InsightConversation = Schema<"SessionPublic">;
type ToolCallResult = Schema<"ToolCallResultPublic">;

/** How many analyses a page of the list holds (the endpoint allows 1 to 100). */
const PAGE_SIZE = 20;

export const insightChatKeys = {
  all: ["conversation-insights", "chat"] as const,
  list: (target: InsightTarget) =>
    [...insightChatKeys.all, "list", target.type, target.id] as const,
  conversation: (sessionId: string) => [...insightChatKeys.all, "conversation", sessionId] as const
};

function targetQuery(target: InsightTarget): { assistant_id?: string; group_chat_id?: string } {
  return target.type === "group-chat" ? { group_chat_id: target.id } : { assistant_id: target.id };
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) return response.json();
  const text = await response.text();
  return text.length > 0 ? text : undefined;
}

/** One request; a refusal throws the EneoApiError every other request produces. */
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  const body = await readBody(response);
  if (!response.ok) throw apiErrorFromResponse(response, body);
  return body as T;
}

/** `GET /`: the caller's own analyses of the target, newest first, a page at a time. */
export function insightConversationsQueryOptions(target: InsightTarget) {
  return infiniteQueryOptions({
    ...cursorPagination,
    queryKey: insightChatKeys.list(target),
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({
        ...targetQuery(target),
        limit: String(PAGE_SIZE)
      });
      if (pageParam) params.set("cursor", pageParam);
      return request<InsightConversationPage>(`${CHAT_PATH}/?${params}`, { signal });
    }
  });
}

/**
 * `GET /{session_id}/`: one analysis with its turns. Read fresh each time it
 * is opened, and never retried: a removed analysis (410) or one that is not
 * the caller's will not appear on a retry.
 */
export function insightConversationQueryOptions(sessionId: string) {
  return queryOptions({
    queryKey: insightChatKeys.conversation(sessionId),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    queryFn: ({ signal }) =>
      request<InsightConversation>(`${CHAT_PATH}/${encodeURIComponent(sessionId)}/`, { signal })
  });
}

/** `DELETE /{session_id}/`: answers 204. */
export async function deleteInsightConversation(sessionId: string): Promise<void> {
  await request<undefined>(`${CHAT_PATH}/${encodeURIComponent(sessionId)}/`, {
    method: "DELETE"
  });
}

/** `GET /{session_id}/tool-calls/{tool_call_id}/result/`: a call's result text, read when its row opens. */
export const insightToolResults: ToolResultSource = {
  scope: "conversation-insights-chat",
  read: async (sessionId, toolCallId) => {
    const response = await request<ToolCallResult>(
      `${CHAT_PATH}/${encodeURIComponent(sessionId)}/tool-calls/${encodeURIComponent(toolCallId)}/result/`
    );
    return response.result ?? null;
  }
};

/** The browser's IANA time zone. */
function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** The analysis as ChatView talks to it, with the period its questions carry. */
export type InsightConversationApi = ConversationApi & {
  /** The period every question sent from now on carries (the picker's). */
  setSelectedRange: (range: InsightSelectedRange | null) => void;
};

/**
 * The analysis as ChatView talks to it. A turn without a session starts an
 * analysis of the target ChatView names (`assistant_id` or `group_chat_id`)
 * with the browser's time zone; one with a session continues it. Each turn
 * carries the period set last (`setSelectedRange`), read when it is sent.
 */
export function insightConversationApi(
  initialRange: InsightSelectedRange | null
): InsightConversationApi {
  let selectedRange = initialRange;
  return {
    transport: createChatTransport({
      request: ({ question, options }) => {
        const range = selectedRange ?? undefined;
        if (options.session_id) {
          const body: InsightChatContinueRequest = {
            question,
            stream: true,
            selected_range: range
          };
          return { api: `${CHAT_PATH}/${encodeURIComponent(options.session_id)}/`, body };
        }
        const body: InsightChatStartRequest = {
          ...(options.group_chat_id
            ? { group_chat_id: options.group_chat_id }
            : { assistant_id: options.assistant_id ?? undefined }),
          question,
          timezone: browserTimeZone(),
          stream: true,
          selected_range: range
        };
        return { api: `${CHAT_PATH}/`, body };
      }
    }),
    toolResults: insightToolResults,
    draftScope: "insights",
    setSelectedRange: (range) => {
      selectedRange = range;
    }
  };
}
