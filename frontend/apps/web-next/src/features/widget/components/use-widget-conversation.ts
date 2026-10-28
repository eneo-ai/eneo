import type { ConversationMessage, WidgetClient } from "@eneo/eneo-js";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Callbacks = NonNullable<Parameters<WidgetClient["conversations"]["ask"]>[0]["callbacks"]>;

/** Tool calls as the backend reports them while an answer streams. */
export type LiveToolCall = {
  server_name: string;
  tool_name: string;
  title?: string | null;
  arguments?: Record<string, unknown> | null;
  tool_call_id?: string | null;
  approved?: boolean | null;
  result_status?: string | null;
  purpose?: string | null;
  is_internal?: boolean | null;
  is_bundled?: boolean | null;
};

/** A message in the widget: the stored shape plus the streaming tool calls. */
export type WidgetMessage = ConversationMessage & { mcp_tool_calls?: LiveToolCall[] };

export type WidgetFeedbackValue = { value: 1 | -1; text?: string | null };

export type WidgetConversation = {
  id: string | null;
  messages: WidgetMessage[];
  /** The vote the server holds for a restored conversation. */
  feedback: WidgetFeedbackValue | null;
};

const EMPTY: WidgetConversation = { id: null, messages: [], feedback: null };

/** How one question ended: with an answer, or with an error before or after it began. */
export type AskResult =
  | { status: "done"; sessionId: string; answer: string }
  | { status: "failed"; error: unknown; started: boolean; sessionId?: string };

/**
 * The one conversation a visitor has with the widget, driven by the widget
 * client's `ask` stream: the question is appended once the backend confirms
 * it (first chunk), the answer grows with every text event, and tool calls
 * are kept on the message for the activity line. The text is flushed to
 * React once per frame so a fast stream does not re-render per token.
 */
export function useWidgetConversation(client: WidgetClient) {
  const [conversation, setConversation] = useState<WidgetConversation>(EMPTY);
  const [asking, setAsking] = useState(false);
  // While a remembered conversation is being fetched.
  const [loading, setLoading] = useState(false);
  // What `ask` continues from; only ever used from event handlers, after commit.
  const current = useRef(conversation);
  useEffect(() => {
    current.current = conversation;
  }, [conversation]);
  // Starting over while an answer streams: events from the old stream are dropped.
  const generation = useRef(0);

  useEffect(() => {
    return () => {
      generation.current += 1;
    };
  }, []);

  const ask = useCallback(
    async (question: string): Promise<AskResult> => {
      const mine = ++generation.current;
      const controller = new AbortController();
      const stale = () => generation.current !== mine;
      // The index the new message gets once the first chunk lands.
      const index = current.current.messages.length;
      let started = false;
      let sessionId: string | undefined;
      let answer = "";
      // Tool events can precede the first chunk; they wait for the message.
      const earlyTools: Parameters<NonNullable<Callbacks["onToolCall"]>>[0][] = [];
      let pendingText = "";
      let frame: number | null = null;
      let references: WidgetMessage["references"] | null = null;

      const patch = (update: (message: WidgetMessage) => WidgetMessage) =>
        setConversation((state) => ({
          ...state,
          messages: state.messages.map((message, at) => (at === index ? update(message) : message))
        }));

      const mergeTools = (
        message: WidgetMessage,
        event: Parameters<NonNullable<Callbacks["onToolCall"]>>[0]
      ): WidgetMessage => {
        const calls = [...(message.mcp_tool_calls ?? [])];
        for (const tool of event.tools as LiveToolCall[]) {
          const at = calls.findIndex(
            (existing) => existing.tool_call_id && existing.tool_call_id === tool.tool_call_id
          );
          if (at >= 0) calls[at] = { ...calls[at], ...tool };
          else calls.push(tool);
        }
        const known = new Set((message.mcp_tool_references ?? []).map((ref) => ref.id));
        const added = (event.mcp_tool_references ?? []).filter((ref) => !known.has(ref.id));
        return {
          ...message,
          mcp_tool_calls: calls,
          mcp_tool_references: [...(message.mcp_tool_references ?? []), ...added]
        };
      };

      const flush = () => {
        frame = null;
        if (!pendingText && !references) return;
        const text = pendingText;
        const refs = references;
        pendingText = "";
        references = null;
        patch((message) => ({
          ...message,
          answer: message.answer + text,
          ...(refs ? { references: refs } : {})
        }));
      };
      const scheduleFlush = () => {
        if (frame !== null) return;
        frame =
          typeof requestAnimationFrame === "function"
            ? requestAnimationFrame(flush)
            : (setTimeout(flush, 0) as unknown as number);
      };

      setAsking(true);
      try {
        const final = await client.conversations.ask({
          conversation: { id: current.current.id },
          question,
          abortController: controller,
          callbacks: {
            onFirstChunk: (chunk) => {
              if (stale()) return controller.abort();
              started = true;
              sessionId = chunk.session_id;
              const message = earlyTools.reduce(mergeTools, {
                ...chunk,
                question,
                answer: "",
                mcp_tool_references: chunk.mcp_tool_references ?? [],
                mcp_tool_calls: []
              } as WidgetMessage);
              setConversation((state) => ({
                ...state,
                id: chunk.session_id,
                messages: [...state.messages.slice(0, index), message]
              }));
            },
            onText: (text) => {
              if (stale()) return controller.abort();
              pendingText += text.answer;
              answer += text.answer;
              references = text.references;
              scheduleFlush();
            },
            onToolCall: (event) => {
              if (stale()) return;
              if (!started) {
                earlyTools.push(event);
                return;
              }
              flush();
              patch((message) => mergeTools(message, event));
            }
          }
        });
        // The stream's own view of the answer is authoritative; the text
        // events are what the visitor saw arrive.
        answer = final.answer ?? answer;
        return sessionId
          ? { status: "done", sessionId, answer }
          : { status: "failed", error: new Error("The answer never started"), started: false };
      } catch (error) {
        return { status: "failed", error, started, sessionId };
      } finally {
        if (frame !== null && typeof cancelAnimationFrame === "function") {
          cancelAnimationFrame(frame);
          frame = null;
        }
        if (!stale()) {
          flush();
          setAsking(false);
        }
      }
    },
    [client]
  );

  const load = useCallback(
    async (sessionId: string): Promise<void> => {
      const mine = ++generation.current;
      setLoading(true);
      try {
        const loaded = await client.conversations.get({ id: sessionId });
        if (generation.current !== mine) return;
        setConversation({
          id: loaded.id,
          messages: (loaded.messages ?? []) as WidgetMessage[],
          feedback: (loaded.feedback as WidgetFeedbackValue | null | undefined) ?? null
        });
      } finally {
        if (generation.current === mine) setLoading(false);
      }
    },
    [client]
  );

  const reset = useCallback(() => {
    generation.current += 1;
    setAsking(false);
    setLoading(false);
    setConversation(EMPTY);
  }, []);

  return useMemo(
    () => ({ conversation, asking, loading, ask, load, reset }),
    [conversation, asking, loading, ask, load, reset]
  );
}
