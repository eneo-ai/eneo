"use client";

import { useEffect, useRef, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type PreflightState = Schema<"PreflightResponse"> | null;

const DEBOUNCE_MS = 400;

/**
 * Debounced token preflight for the context bar. Stale responses are
 * discarded via a generation counter (partner/session switches mid-flight).
 */
export function usePreflight(request: {
  question: string;
  fileIds: string[];
  sessionId?: string | null;
  assistantId?: string | null;
  groupChatId?: string | null;
}): PreflightState {
  const [preflight, setPreflight] = useState<PreflightState>(null);
  const generation = useRef(0);

  const { question, sessionId, assistantId, groupChatId } = request;
  const fileKey = request.fileIds.join(",");

  useEffect(() => {
    const current = ++generation.current;
    if (!question && !fileKey) return;

    const timer = setTimeout(async () => {
      try {
        const response = await unwrap(
          browserApi.POST("/api/v1/conversations/preflight", {
            body: {
              question,
              file_ids: fileKey ? fileKey.split(",") : [],
              session_id: sessionId ?? null,
              assistant_id: assistantId ?? null,
              group_chat_id: groupChatId ?? null
            }
          })
        );
        if (generation.current === current) setPreflight(response);
      } catch {
        // Preflight is best-effort UX; stay silent on errors (incl. 429).
      }
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [question, fileKey, sessionId, assistantId, groupChatId]);

  // Empty input: report no pending cost (derived, not reset via setState).
  return question || fileKey ? preflight : null;
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
  const projectedTotal =
    lockedInputTokens + lockedOutputTokens + pendingTextTokens + pendingFileTokens;
  return {
    contextLimit,
    // Per-segment breakdown for the context-usage bar: the last turn's locked
    // input/output (provider prompt + reply) plus the pending estimate split
    // into the user's text and their attached files.
    lockedInputTokens,
    lockedOutputTokens,
    pendingTextTokens,
    pendingFileTokens,
    usedTokens: projectedTotal,
    willExceedContext: contextLimit > 0 && projectedTotal > contextLimit
  };
}

export type ContextUsage = ReturnType<typeof deriveContextUsage>;
