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
  settings?: Schema<"ConversationSettings">;
  settingsRevision?: number;
  disabled?: boolean;
}): PreflightState {
  const [result, setResult] = useState<{ context: string; value: PreflightState } | null>(null);
  const generation = useRef(0);

  const { question, sessionId, assistantId, groupChatId, settings, settingsRevision, disabled } =
    request;
  const settingsKey = JSON.stringify(settings);
  const fileKey = request.fileIds.join(",");
  // An estimate stays valid while the same conversation context is typed
  // into; a model, revision or partner change invalidates it at once.
  const contextKey = JSON.stringify([
    sessionId,
    assistantId,
    groupChatId,
    settingsKey,
    settingsRevision
  ]);

  useEffect(() => {
    const current = ++generation.current;
    if (disabled || (!question && !fileKey)) return;

    const timer = setTimeout(async () => {
      try {
        const response = await unwrap(
          browserApi.POST("/api/v1/conversations/preflight", {
            body: {
              question,
              file_ids: fileKey ? fileKey.split(",") : [],
              session_id: sessionId ?? null,
              assistant_id: assistantId ?? null,
              group_chat_id: groupChatId ?? null,
              settings,
              settings_revision: settingsRevision
            }
          })
        );
        if (generation.current === current) setResult({ context: contextKey, value: response });
      } catch {
        // Preflight is best-effort UX; stay silent on errors (incl. 429).
      }
    }, DEBOUNCE_MS);

    return () => {
      generation.current = current + 1;
      clearTimeout(timer);
    };
    // Compare settings by value, not an incidental object identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    question,
    fileKey,
    sessionId,
    assistantId,
    groupChatId,
    settingsKey,
    settingsRevision,
    disabled
  ]);

  // Empty input: report no pending cost (derived, not reset via setState).
  return !disabled && (question || fileKey) && result?.context === contextKey ? result.value : null;
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
