// @vitest-environment jsdom
/**
 * The insights chat's endpoints: the typed requests for the list, an
 * analysis, its deletion and a tool call's result, the bodies a turn sends,
 * and its answer stream held to the chat stream contract
 * (src/lib/chat/CONTRACT.md).
 */
import { Chat } from "@ai-sdk/react";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, isDerivedSourceRemoved } from "@/lib/api/errors";
import { loadFixtures, sseResponse, toSseBody } from "@/lib/chat/contract-fixtures";
import type { EneoUIMessage } from "@/lib/chat/types";
import {
  deleteInsightConversation,
  insightConversationApi,
  insightConversationQueryOptions,
  insightConversationsQueryOptions,
  insightToolResults
} from "./insights-chat-api";

const apiFetch = vi.hoisted(() => vi.fn<typeof fetch>());
vi.mock("@/lib/api/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/base")>()),
  apiFetch
}));

afterEach(() => {
  apiFetch.mockReset();
  vi.restoreAllMocks();
});

const CHAT = "/api/v1/analysis/conversation-insights/chat";
const SESSION = "11111111-1111-1111-1111-111111111111";
const range = { start: "2026-10-12" as const, end: "2026-11-11" as const };

/** The request apiFetch was given: its URL, method and JSON body. */
function sent(index = 0) {
  const [input, init] = apiFetch.mock.calls[index]!;
  return {
    url: String(input),
    method: init?.method ?? "GET",
    body: typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined
  };
}

/** A conversation in the chat stream contract's tool-call fixture, with the analysis' own tool. */
function analysisStream() {
  const fixture = loadFixtures().find((item) => item.name === "tool-call-with-output")!;
  const events = fixture.events.map((event) => {
    if (!String(event.type).startsWith("tool-")) return event;
    const eneo = (event.providerMetadata as { eneo: Record<string, unknown> }).eneo;
    return {
      ...event,
      ...(event.toolName ? { toolName: "search_questions" } : {}),
      ...(event.input ? { input: { query: "parkering", start: "x", end: "y" } } : {}),
      providerMetadata: { eneo: { ...eneo, server_name: "insights", title: "Search questions" } }
    };
  });
  return { fixture, body: toSseBody(events) };
}

async function ask(
  analysis: ReturnType<typeof insightConversationApi>,
  body: Record<string, unknown>,
  response: Response = sseResponse(analysisStream().body)
) {
  apiFetch.mockResolvedValueOnce(response);
  const chat = new Chat<EneoUIMessage>({ transport: analysis.transport, onError: () => {} });
  await chat.sendMessage({ text: "Vad frågar folk om parkering?" }, { body });
  return chat;
}

describe("a question to the analysis", () => {
  it("starts an analysis of the assistant with the period and the browser's time zone", async () => {
    const chat = await ask(insightConversationApi(range), {
      session_id: null,
      assistant_id: "assistant-1",
      group_chat_id: null,
      files: [],
      allow_questions: true
    });
    expect(chat.status).toBe("ready");
    expect(sent()).toEqual({
      url: `${CHAT}/`,
      method: "POST",
      body: {
        assistant_id: "assistant-1",
        question: "Vad frågar folk om parkering?",
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        stream: true,
        selected_range: range
      }
    });
  });

  it("starts an analysis of a group chat", async () => {
    await ask(insightConversationApi(range), {
      session_id: null,
      assistant_id: null,
      group_chat_id: "group-1",
      files: []
    });
    expect(sent().body).toMatchObject({ group_chat_id: "group-1" });
    expect(sent().body).not.toHaveProperty("assistant_id");
  });

  it("continues an analysis with the period set since, and nothing else", async () => {
    const analysis = insightConversationApi(range);
    analysis.setSelectedRange({ start: "2026-11-04", end: "2026-11-11" });
    await ask(analysis, { session_id: SESSION, assistant_id: null, files: [] });
    expect(sent()).toEqual({
      url: `${CHAT}/${SESSION}/`,
      method: "POST",
      body: {
        question: "Vad frågar folk om parkering?",
        stream: true,
        selected_range: { start: "2026-11-04", end: "2026-11-11" }
      }
    });
  });

  it("settles the shared stream contract's fixture as the chat API does", async () => {
    const { fixture } = analysisStream();
    const chat = await ask(insightConversationApi(null), { session_id: SESSION, files: [] });
    expect(sent().body).not.toHaveProperty("selected_range");
    const parts = chat.lastMessage!.parts;
    expect(parts.map((part) => part.type)).toEqual(
      fixture.ui.message.parts.map((part) => part.type)
    );
    expect(parts.find((part) => part.type === "dynamic-tool")).toMatchObject({
      toolName: "search_questions",
      state: "output-available",
      input: { query: "parkering" },
      resultProviderMetadata: { eneo: { server_name: "insights", result_status: "succeeded" } }
    });
  });

  it("fails a question to an analysis that was removed with its conversations", async () => {
    const chat = await ask(
      insightConversationApi(range),
      { session_id: SESSION, files: [] },
      Response.json(
        { message: "Gone", code: "derived_source_removed" },
        { status: 410, headers: { "x-trace-id": "trace-1" } }
      )
    );
    expect(chat.status).toBe("error");
    expect(chat.error).toBeInstanceOf(EneoApiError);
    expect(isDerivedSourceRemoved(chat.error)).toBe(true);
  });
});

/** A typed request's result, as `browserApi` resolves it. */
type ApiResult = { data?: unknown; error?: unknown; response: Response };

const answered = (data: unknown, status = 200): ApiResult => ({
  data,
  response: new Response(null, { status })
});

const refused = (status: number, error: unknown): ApiResult => ({
  error,
  response: Response.json(error, { status, headers: { "x-trace-id": "trace-1" } })
});

function answerGets(...results: ApiResult[]) {
  const get = vi.spyOn(browserApi, "GET");
  // A resolved value typed on every route of the API is more than the
  // compiler will instantiate, so each answer is given as an implementation.
  for (const result of results) {
    get.mockImplementationOnce((() => Promise.resolve(result)) as never);
  }
  return get;
}

describe("the analyses", () => {
  const target = { type: "assistant" as const, id: "assistant-1" };

  it("lists the target's analyses a page at a time", async () => {
    const client = new QueryClient();
    const get = answerGets(
      answered({
        items: [{ id: SESSION, name: "Vad frågar folk om?" }],
        total_count: 21,
        next_cursor: "2026-11-01T10:00:00+00:00_cursor"
      }),
      answered({ items: [], total_count: 21 })
    );
    const options = insightConversationsQueryOptions(target);
    const first = await client.infiniteQuery(options);
    expect(first.pages[0]!.items).toHaveLength(1);
    expect(get).toHaveBeenNthCalledWith(1, `${CHAT}/`, {
      params: { query: { assistant_id: "assistant-1", limit: 20, cursor: undefined } },
      signal: expect.any(AbortSignal)
    });
    expect(options.getNextPageParam(first.pages[0]!, first.pages, undefined, [undefined])).toBe(
      "2026-11-01T10:00:00+00:00_cursor"
    );

    // The next page continues from the cursor the last one gave, as given.
    await options.queryFn!({
      pageParam: "2026-11-01T10:00:00+00:00_cursor",
      signal: new AbortController().signal
    } as never);
    expect(get).toHaveBeenNthCalledWith(2, `${CHAT}/`, {
      params: {
        query: {
          assistant_id: "assistant-1",
          limit: 20,
          cursor: "2026-11-01T10:00:00+00:00_cursor"
        }
      },
      signal: expect.any(AbortSignal)
    });
  });

  it("lists a group chat's analyses by its id", async () => {
    const get = answerGets(answered({ items: [], total_count: 0 }));
    await new QueryClient().infiniteQuery(
      insightConversationsQueryOptions({ type: "group-chat", id: "group-1" })
    );
    expect(get).toHaveBeenCalledWith(`${CHAT}/`, {
      params: { query: { group_chat_id: "group-1", limit: 20, cursor: undefined } },
      signal: expect.any(AbortSignal)
    });
  });

  it("opens one analysis, and says when it was removed with its conversations", async () => {
    const client = new QueryClient();
    const get = answerGets(
      answered({ id: SESSION, name: "Fråga", messages: [] }),
      refused(410, { message: "Gone", code: "derived_source_removed" })
    );
    await expect(client.query(insightConversationQueryOptions(SESSION))).resolves.toEqual({
      id: SESSION,
      name: "Fråga",
      messages: []
    });
    expect(get).toHaveBeenCalledWith(`${CHAT}/{session_id}/`, {
      params: { path: { session_id: SESSION } },
      signal: expect.any(AbortSignal)
    });

    const removed = await client
      .query(insightConversationQueryOptions("other"))
      .catch((error: unknown) => error);
    expect(removed).toBeInstanceOf(EneoApiError);
    expect(isDerivedSourceRemoved(removed)).toBe(true);
    expect((removed as EneoApiError).traceId).toBe("trace-1");
  });

  it("deletes an analysis, and refuses as every request does", async () => {
    const remove = vi.spyOn(browserApi, "DELETE");
    remove.mockResolvedValueOnce(answered(undefined, 204) as never);
    await deleteInsightConversation(SESSION);
    expect(remove).toHaveBeenCalledWith(`${CHAT}/{session_id}/`, {
      params: { path: { session_id: SESSION } }
    });

    remove.mockResolvedValueOnce(
      refused(403, { message: "Not yours", code: "forbidden_action" }) as never
    );
    const error = await deleteInsightConversation(SESSION).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(EneoApiError);
    expect((error as EneoApiError).status).toBe(403);
  });

  it("reads a tool call's result from the analysis", async () => {
    const get = answerGets(
      answered({ tool_call_id: "call-1", result: "Questions 1-2 of 2", mcp_tool_name: null })
    );
    await expect(insightToolResults.read(SESSION, "call-1")).resolves.toBe("Questions 1-2 of 2");
    expect(get).toHaveBeenCalledWith(`${CHAT}/{session_id}/tool-calls/{tool_call_id}/result/`, {
      params: { path: { session_id: SESSION, tool_call_id: "call-1" } }
    });
  });
});
