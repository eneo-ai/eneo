import { EneoError } from "@eneo/eneo-js";
import { isHttpError } from "@sveltejs/kit";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { toAppError } from "$lib/core/errors/toAppError";
import { load as loadSpace } from "./spaces/[spaceId]/chat/+page";
import { load as loadDashboard } from "./dashboard/[assistantId]/[[sessionId]]/+page";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function fixture(hasSession = true) {
  const partner = { id: "assistant-1", type: "assistant", is_help_assistant: false };
  const conversation = { id: "session-1", name: "Saved conversation", messages: [] };
  const history = {
    items: [{ id: conversation.id, name: conversation.name }],
    count: 1,
    total_count: 2,
    next_cursor: "next-page"
  };
  const getPartner = vi.fn(async () => partner);
  const getSession = vi.fn(async () => conversation);
  const listSessions = vi.fn(async () => history);
  const getGroup = vi.fn(async () => ({ ...partner, type: "group-chat" }));
  const currentSpace = { default_assistant: { ...partner, permissions: ["read"] } };
  const input = {
    parent: async () => ({
      eneo: {
        assistants: { get: getPartner, getSession },
        conversations: { get: getSession, list: listSessions },
        groupChats: { get: getGroup }
      },
      currentSpace
    }),
    params: {
      spaceId: "space-1",
      assistantId: partner.id,
      sessionId: hasSession ? conversation.id : undefined
    },
    url: new URL(
      `https://eneo.example/spaces/space-1/chat?type=assistant&id=${partner.id}${hasSession ? `&session_id=${conversation.id}` : ""}`
    )
  };
  return {
    input,
    partner,
    conversation,
    history,
    currentSpace,
    getPartner,
    getSession,
    listSessions,
    getGroup
  };
}

const unhandledRejection = vi.fn();
beforeEach(() => {
  unhandledRejection.mockClear();
  process.on("unhandledRejection", unhandledRejection);
});
afterEach(async () => {
  try {
    // Rejections must stay observed even after the page load has already failed.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(unhandledRejection).not.toHaveBeenCalled();
  } finally {
    process.off("unhandledRejection", unhandledRejection);
  }
});

describe.each([
  { name: "Space chat", load: loadSpace },
  { name: "Dashboard chat", load: loadDashboard }
])("$name loader", ({ load }) => {
  test("loads in parallel and returns settled conversation and history data", async () => {
    const data = fixture();
    const partner = deferred<typeof data.partner>();
    const session = deferred<typeof data.conversation>();
    const history = deferred<typeof data.history>();
    data.getPartner.mockReturnValue(partner.promise);
    data.getSession.mockReturnValue(session.promise);
    data.listSessions.mockReturnValue(history.promise);

    const result = load(data.input as never);
    await vi.waitFor(() => {
      expect(data.getPartner).toHaveBeenCalledOnce();
      expect(data.getSession).toHaveBeenCalledOnce();
      expect(data.listSessions).toHaveBeenCalledOnce();
    });

    partner.resolve(data.partner);
    history.resolve(data.history);
    session.resolve(data.conversation);
    expect(await result).toMatchObject({
      chatPartner: data.partner,
      initialConversation: data.conversation,
      initialHistory: data.history
    });
  });

  test("opens a new conversation without a session lookup", async () => {
    const data = fixture(false);
    expect(await load(data.input as never)).toMatchObject({
      initialConversation: null,
      initialHistory: data.history
    });
    expect(data.getSession).not.toHaveBeenCalled();
  });

  test.each([403, 404, 500])(
    "preserves a session %i for SvelteKit error handling",
    async (status) => {
      const data = fixture();
      const failure = new EneoError(
        "Conversation unavailable",
        "RESPONSE",
        status,
        status === 404 ? 9000 : 0,
        undefined,
        { endpoint: "GET@/api/v1/conversations/session-1/" },
        new Headers({ "x-trace-id": "0af7651916cd43dd8448eb211c80319c" })
      );
      data.getSession.mockRejectedValue(failure);

      await expect(load(data.input as never)).rejects.toBe(failure);
      expect(toAppError(failure, { status: 500, message: "Internal Error" })).toMatchObject({
        status,
        code: status === 404 ? 9000 : 0,
        traceId: "0af7651916cd43dd8448eb211c80319c"
      });

      // A failed URL does not prevent the next valid page load from succeeding.
      data.getSession.mockResolvedValue(data.conversation);
      expect(await load(data.input as never)).toMatchObject({
        initialConversation: data.conversation
      });
    }
  );

  test("routes a network failure through the page load", async () => {
    const data = fixture();
    const failure = new TypeError("fetch failed");
    data.getSession.mockRejectedValue(failure);
    await expect(load(data.input as never)).rejects.toBe(failure);
  });

  test("reports a history failure instead of returning an Error as history data", async () => {
    const data = fixture();
    const failure = new Error("history unavailable");
    data.listSessions.mockRejectedValue(failure);
    await expect(load(data.input as never)).rejects.toBe(failure);
  });

  test.each(["session", "history", "partner"] as const)(
    "observes an early %s failure and later failures from the other requests",
    async (first) => {
      const data = fixture();
      const partner = deferred<typeof data.partner>();
      const session = deferred<typeof data.conversation>();
      const history = deferred<typeof data.history>();
      data.getPartner.mockReturnValue(partner.promise);
      data.getSession.mockReturnValue(session.promise);
      data.listSessions.mockReturnValue(history.promise);

      const requests = { partner, session, history };
      const failure = new Error(`${first} unavailable`);
      const result = expect(load(data.input as never)).rejects.toBe(failure);
      await vi.waitFor(() => expect(data.getSession).toHaveBeenCalledOnce());
      requests[first].reject(failure);

      // Give Node an event-loop turn while the other two requests are pending.
      await new Promise((resolve) => setTimeout(resolve, 0));
      for (const [name, request] of Object.entries(requests)) {
        if (name !== first) request.reject(new Error(`${name} also unavailable`));
      }
      await result;
    }
  );
});

describe("Space chat access", () => {
  test("does not request conversations without personal-chat read access", async () => {
    const data = fixture();
    data.input.url.searchParams.delete("type");
    data.currentSpace.default_assistant.permissions = [];

    expect(await loadSpace(data.input as never)).toMatchObject({
      accessDenied: true,
      initialConversation: null,
      initialHistory: { items: [], count: 0, total_count: 0, next_cursor: null }
    });
    expect(data.getSession).not.toHaveBeenCalled();
    expect(data.listSessions).not.toHaveBeenCalled();
  });

  test("still loads group-chat conversations", async () => {
    const data = fixture();
    data.input.url.searchParams.set("type", "group-chat");

    expect(await loadSpace(data.input as never)).toMatchObject({
      chatPartner: { type: "group-chat" },
      initialConversation: data.conversation,
      initialHistory: data.history
    });
    expect(data.getGroup).toHaveBeenCalledOnce();
    expect(data.getPartner).not.toHaveBeenCalled();
  });

  test("still refuses to open a help assistant as a chat", async () => {
    const data = fixture();
    data.partner.is_help_assistant = true;
    const failure = await Promise.resolve(loadSpace(data.input as never)).catch(
      (error: unknown) => error
    );
    expect(isHttpError(failure, 404)).toBe(true);
  });
});
