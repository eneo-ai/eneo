import { useEffect, useRef, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type PreflightState = Schema<"PreflightResponse"> | null;

const DEBOUNCE_MS = 400;

/**
 * Debounced token preflight for the context bar. Stale responses are
 * aborted on key changes and discarded if they arrive after cancellation.
 */
export function usePreflight(request: {
  question: string;
  fileIds: string[];
  sessionId?: string | null;
  assistantId?: string | null;
  groupChatId?: string | null;
  revision?: string | null;
}): PreflightState {
  const [preflight, setPreflight] = useState<{ key: string; response: PreflightState } | null>(
    null
  );
  const generation = useRef(0);

  const { question, sessionId, assistantId, groupChatId } = request;
  const fileKey = request.fileIds.join(",");

  const key = JSON.stringify([
    question,
    fileKey,
    sessionId ?? null,
    assistantId ?? null,
    groupChatId ?? null,
    request.revision ?? null
  ]);
  const shouldRequest = Boolean(question || fileKey || (assistantId && !sessionId && !groupChatId));

  useEffect(() => {
    const current = ++generation.current;
    if (!shouldRequest) return;
    const controller = new AbortController();

    const timer = setTimeout(async () => {
      try {
        const response = await unwrap(
          browserApi.POST("/api/v1/conversations/preflight", {
            signal: controller.signal,
            body: {
              question,
              file_ids: fileKey ? fileKey.split(",") : [],
              session_id: sessionId ?? null,
              assistant_id: assistantId ?? null,
              group_chat_id: groupChatId ?? null
            }
          })
        );
        if (!controller.signal.aborted && generation.current === current) {
          setPreflight({ key, response });
        }
      } catch {
        // Preflight is best-effort UX; stay silent on errors (incl. 429).
      }
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [question, fileKey, sessionId, assistantId, groupChatId, key, shouldRequest]);

  // A new draft/partner/session must not expose the old estimate while waiting.
  return shouldRequest && preflight?.key === key ? preflight.response : null;
}

/**
 * Context-usage derivation ported from the Svelte ChatService: locked tokens
 * from the last persisted turn plus the pending preflight cost, against the
 * effective context limit.
 */
export function deriveContextUsage({
  preflight,
  lockedInputTokens,
  lockedOutputTokens,
  fallbackContextLimit
}: {
  preflight: PreflightState;
  lockedInputTokens: number;
  lockedOutputTokens: number;
  fallbackContextLimit: number;
}) {
  const contextLimit = preflight?.context_window || fallbackContextLimit || 0;
  const pendingTextTokens = preflight?.input_tokens ?? 0;
  const pendingFileTokens = preflight?.file_tokens ?? 0;
  const assistantPromptTokens = preflight?.prompt_tokens ?? 0;
  const assistantAttachmentTokens = preflight?.assistant_attachment_tokens ?? 0;
  // The backend includes the Skill context in prompt_tokens.
  const skillContextTokens = preflight?.skill_context_tokens ?? 0;
  const projectedTotal =
    lockedInputTokens +
    lockedOutputTokens +
    pendingTextTokens +
    pendingFileTokens +
    assistantPromptTokens +
    assistantAttachmentTokens;
  return {
    contextLimit,
    // Per-segment breakdown for the context-usage bar: the last turn's locked
    // input/output (provider prompt + reply) plus the pending estimate split
    // into the user's text and their attached files.
    lockedInputTokens,
    lockedOutputTokens,
    pendingTextTokens,
    pendingFileTokens,
    assistantPromptTokens,
    assistantAttachmentTokens,
    skillContextTokens,
    usedTokens: projectedTotal,
    willExceedContext: contextLimit > 0 && projectedTotal > contextLimit
  };
}

export type ContextUsage = ReturnType<typeof deriveContextUsage>;
