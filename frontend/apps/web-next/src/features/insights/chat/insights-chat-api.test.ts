// @vitest-environment jsdom
/**
 * The insights chat's endpoints as the UI expects the backend to serve them
 * (the paths, bodies and answers this module writes by hand), and its
 * answer stream held to the chat stream contract (src/lib/chat/CONTRACT.md).
 */
import { Chat } from "@ai-sdk/react";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
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

afterEach(() => apiFetch.mockReset());

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

describe("the analyses", () => {
  const target = { type: "assistant" as const, id: "assistant-1" };

  it("lists the target's analyses a page at a time", async () => {
    const client = new QueryClient();
    apiFetch.mockResolvedValueOnce(
      Response.json({
        items: [{ id: SESSION, name: "Vad frågar folk om?" }],
        total_count: 21,
        next_cursor: "2026-11-01T10:00:00Z"
      })
    );
    apiFetch.mockResolvedValueOnce(Response.json({ items: [], total_count: 21 }));
    const options = insightConversationsQueryOptions(target);
    const first = await client.infiniteQuery(options);
    expect(first.pages[0]!.items).toHaveLength(1);
    expect(sent(0).url).toBe(`${CHAT}/?assistant_id=assistant-1&limit=20`);
    expect(options.getNextPageParam(first.pages[0]!, first.pages, undefined, [undefined])).toBe(
      "2026-11-01T10:00:00Z"
    );

    // The next page continues from the cursor the last one gave.
    await options.queryFn!({
      pageParam: "2026-11-01T10:00:00Z",
      signal: new AbortController().signal
    } as never);
    expect(sent(1).url).toBe(
      `${CHAT}/?assistant_id=assistant-1&limit=20&cursor=2026-11-01T10%3A00%3A00Z`
    );
  });

  it("lists a group chat's analyses by its id", async () => {
    apiFetch.mockResolvedValueOnce(Response.json({ items: [], total_count: 0 }));
    await new QueryClient().infiniteQuery(
      insightConversationsQueryOptions({ type: "group-chat", id: "group-1" })
    );
    expect(sent().url).toBe(`${CHAT}/?group_chat_id=group-1&limit=20`);
  });

  it("opens one analysis, and says when it was removed with its conversations", async () => {
    const client = new QueryClient();
    apiFetch.mockResolvedValueOnce(Response.json({ id: SESSION, name: "Fråga", messages: [] }));
    await expect(client.query(insightConversationQueryOptions(SESSION))).resolves.toEqual({
      id: SESSION,
      name: "Fråga",
      messages: []
    });
    expect(sent()).toEqual({ url: `${CHAT}/${SESSION}/`, method: "GET", body: undefined });

    apiFetch.mockResolvedValueOnce(
      Response.json({ message: "Gone", code: "derived_source_removed" }, { status: 410 })
    );
    const refused = await client
      .query(insightConversationQueryOptions("other"))
      .catch((error: unknown) => error);
    expect(isDerivedSourceRemoved(refused)).toBe(true);
  });

  it("deletes an analysis", async () => {
    apiFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await deleteInsightConversation(SESSION);
    expect(sent()).toEqual({ url: `${CHAT}/${SESSION}/`, method: "DELETE", body: undefined });
  });

  it("reads a tool call's result from the analysis", async () => {
    apiFetch.mockResolvedValueOnce(
      Response.json({ tool_call_id: "call-1", result: "Questions 1-2 of 2", mcp_tool_name: null })
    );
    await expect(insightToolResults.read(SESSION, "call-1")).resolves.toBe("Questions 1-2 of 2");
    expect(sent().url).toBe(`${CHAT}/${SESSION}/tool-calls/call-1/result/`);
  });
});
