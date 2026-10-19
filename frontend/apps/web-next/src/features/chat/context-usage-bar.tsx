"use client";

import { Button } from "@astryxdesign/core/Button";
import { Popover } from "@astryxdesign/core/Popover";
import { EyeOff, Info, TriangleAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useState, useSyncExternalStore } from "react";
import type { ContextUsage } from "@/lib/chat/use-preflight";
import { cn } from "@/lib/utils";

const PINNED_STORAGE_KEY = "contextUsageBarPinned";

// localStorage-backed "always show" preference, read via useSyncExternalStore
// so there's no setState-in-effect and no hydration mismatch (server
// snapshot = not pinned, which renders nothing).
const pinListeners = new Set<() => void>();

function subscribePinned(callback: () => void) {
  pinListeners.add(callback);
  return () => pinListeners.delete(callback);
}

function readPinned() {
  try {
    return window.localStorage.getItem(PINNED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

/**
 * Whether the user asked to always see the meter (the chat menu's "Visa
 * kontextanvändning"). Without it the meter appears on its own only from
 * SHOW_FROM_PERCENT of the window.
 */
export function useContextUsagePinned(): boolean {
  return useSyncExternalStore(subscribePinned, readPinned, () => false);
}

export function setContextUsagePinned(next: boolean) {
  try {
    window.localStorage.setItem(PINNED_STORAGE_KEY, next ? "true" : "false");
  } catch {
    // Ignore persistence failures (private mode / blocked storage).
  }
  for (const listener of pinListeners) listener();
}

/**
 * Four visually distinct segments, mapped to the eneo chart palette so each
 * keeps contrast against the track and each other in both themes:
 *   locked input  → neutral gray (provider prompt: system + RAG + history)
 *   locked output → green  (model's previous reply)
 *   pending text  → blue   (locally estimated tokens for the current input)
 *   pending files → amber  (locally estimated multimodal/file tokens)
 */
const SEGMENT_CLASS: Record<string, string> = {
  lockedInput: "bg-ax-text-secondary",
  lockedOutput: "bg-ax-purple",
  pendingText: "bg-ax-blue",
  pendingFiles: "bg-ax-orange"
};

/**
 * From this share of the context window the meter shows on its own. Below it
 * the conversation has room and the meter is noise under the composer, so
 * nothing renders unless the user pinned it from the chat menu.
 */
export const SHOW_FROM_PERCENT = 60;

/**
 * Context-usage meter ported from the Svelte `ContextUsageBar`: a segmented
 * progress bar under the composer with a detailed popover breaking the estimate
 * into locked (last turn) vs pending (your text/files) tokens, the running
 * conversation total, and an over-limit warning. Advisory only — the provider
 * validates the final payload. Shown from SHOW_FROM_PERCENT of the window,
 * when the estimate overflows, or always when pinned.
 */
export function ContextUsageBar({
  usage,
  modelName,
  cumulativeTokens,
  turnCount,
  onNewConversation
}: {
  usage: ContextUsage;
  modelName?: string | null;
  cumulativeTokens: number;
  turnCount: number;
  onNewConversation?: () => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const fmt = useMemo(() => {
    const nf = new Intl.NumberFormat(locale === "sv" ? "sv-SE" : "en-US");
    return (value: number) => nf.format(value);
  }, [locale]);

  const pinned = useContextUsagePinned();
  const [open, setOpen] = useState(false);

  const {
    contextLimit,
    lockedInputTokens,
    lockedOutputTokens,
    pendingTextTokens,
    pendingFileTokens,
    usedTokens: projectedTotal,
    willExceedContext: willExceed
  } = usage;

  const pendingTotal = pendingTextTokens + pendingFileTokens;
  const hasUsage =
    contextLimit > 0 && (lockedInputTokens + lockedOutputTokens > 0 || pendingTotal > 0);
  const projectedPercent = contextLimit > 0 ? (projectedTotal / contextLimit) * 100 : 0;

  // Lay segments out left-to-right, capping each so they never overflow the bar.
  const segments = useMemo(() => {
    if (contextLimit <= 0) return [];
    const raw = [
      { key: "lockedInput", tokens: lockedInputTokens },
      { key: "lockedOutput", tokens: lockedOutputTokens },
      { key: "pendingText", tokens: pendingTextTokens },
      { key: "pendingFiles", tokens: pendingFileTokens }
    ];
    let cursor = 0;
    return raw.map((segment) => {
      const widthPct = (segment.tokens / contextLimit) * 100;
      const capped = Math.max(0, Math.min(100 - cursor, widthPct));
      const result = { ...segment, leftPct: cursor, widthPct: capped };
      cursor += capped;
      return result;
    });
  }, [contextLimit, lockedInputTokens, lockedOutputTokens, pendingTextTokens, pendingFileTokens]);

  const hasCumulative = cumulativeTokens > 0 && turnCount > 0;
  const cumulativeSummary =
    turnCount === 1
      ? t("context_usage_cumulative_summary_singular", {
          total: fmt(cumulativeTokens),
          turns: turnCount
        })
      : t("context_usage_cumulative_summary", { total: fmt(cumulativeTokens), turns: turnCount });
  const averagePerTurn = turnCount > 0 ? Math.round(cumulativeTokens / turnCount) : 0;

  function segmentClass(key: string) {
    if (willExceed && (key === "pendingText" || key === "pendingFiles")) return "bg-ax-error";
    return SEGMENT_CLASS[key] ?? "bg-ax-text-secondary";
  }

  // The meter earns its place when the window is filling up; otherwise only a
  // pin from the chat menu shows it.
  const warranted = projectedPercent >= SHOW_FROM_PERCENT || willExceed;
  if (!hasUsage || (!warranted && !pinned)) return null;

  const percentLabel = projectedPercent.toFixed(projectedPercent >= 10 ? 0 : 1);

  const details = (
    <div className="flex flex-col text-xs">
      <div className="border-ax-border border-b pb-3">
        <p className="text-sm font-medium">{t("context_usage_estimate")}</p>
        <p className="text-ax-text-secondary mt-0.5 text-xs tabular-nums">
          ≈ {fmt(projectedTotal)} / {fmt(contextLimit)} {t("chat_tokens_separator")} {percentLabel}%
        </p>
      </div>

      <div className="space-y-3 py-3">
        {(lockedInputTokens > 0 || lockedOutputTokens > 0) && (
          <div className="space-y-1.5">
            <p className="text-ax-text-secondary text-[10px] font-medium tracking-wide uppercase">
              {t("context_usage_section_locked")}
            </p>
            <div className="flex items-baseline justify-between gap-3">
              <span className="flex items-center gap-2">
                <span className="bg-ax-text-secondary inline-block size-2.5 rounded-full" />
                {t("context_usage_label_input")}
              </span>
              <span className="text-ax-text-secondary tabular-nums">{fmt(lockedInputTokens)}</span>
            </div>
            <p className="text-ax-text-secondary ps-[18px] text-[10px] leading-snug">
              {t("context_usage_label_input_hint")}
            </p>
            <div className="flex items-baseline justify-between gap-3">
              <span className="flex items-center gap-2">
                <span className="bg-ax-purple inline-block size-2.5 rounded-full" />
                {t("context_usage_label_output")}
              </span>
              <span className="text-ax-text-secondary tabular-nums">{fmt(lockedOutputTokens)}</span>
            </div>
          </div>
        )}

        {pendingTotal > 0 && (
          <div className="border-ax-border space-y-1.5 border-t pt-3">
            <p className="text-ax-text-secondary text-[10px] font-medium tracking-wide uppercase">
              {t("context_usage_section_pending")}
            </p>
            {pendingTextTokens > 0 && (
              <div className="flex items-baseline justify-between gap-3">
                <span className="flex items-center gap-2">
                  <span className="bg-ax-blue inline-block size-2.5 rounded-full" />
                  {t("context_usage_label_your_text")}
                </span>
                <span className="text-ax-text-secondary tabular-nums">
                  {fmt(pendingTextTokens)}
                </span>
              </div>
            )}
            {pendingFileTokens > 0 && (
              <div className="flex items-baseline justify-between gap-3">
                <span className="flex items-center gap-2">
                  <span className="bg-ax-orange inline-block size-2.5 rounded-full" />
                  {t("context_usage_label_files")}
                </span>
                <span className="text-ax-text-secondary tabular-nums">
                  {fmt(pendingFileTokens)}
                </span>
              </div>
            )}
          </div>
        )}

        {pendingTotal > 0 && (
          <div className="border-ax-border space-y-1.5 border-t pt-3">
            <p className="text-ax-text-secondary text-[10px] font-medium tracking-wide uppercase">
              {t("context_usage_section_excluded")}
            </p>
            <p className="text-ax-text-secondary leading-snug">
              {t("context_usage_excluded_hint")}
            </p>
          </div>
        )}

        {hasCumulative && (
          <div className="border-ax-border space-y-1.5 border-t pt-3">
            <p className="text-ax-text-secondary text-[10px] font-medium tracking-wide uppercase">
              {t("context_usage_section_cumulative")}
            </p>
            <div className="flex items-baseline justify-between gap-3">
              <span>{t("context_usage_cumulative_label")}</span>
              <span className="text-ax-text-secondary tabular-nums">{cumulativeSummary}</span>
            </div>
            {turnCount > 1 && (
              <p className="text-ax-text-secondary text-[10px] leading-snug tabular-nums">
                {t("context_usage_cumulative_average", { average: fmt(averagePerTurn) })}
              </p>
            )}
            <p className="text-ax-text-secondary leading-snug">
              {t("context_usage_cumulative_hint")}
            </p>
          </div>
        )}

        {willExceed && (
          <div className="bg-ax-error-muted text-ax-error rounded-ax-inner flex flex-col gap-2 px-2 py-1.5">
            <div className="flex items-start gap-2">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span className="text-[11px] leading-snug">
                {t("context_usage_will_exceed_estimate")}
              </span>
            </div>
            {onNewConversation && (
              <Button
                label={t("new_conversation")}
                variant="secondary"
                size="sm"
                onClick={() => {
                  setOpen(false);
                  onNewConversation();
                }}
                className="self-start"
              />
            )}
          </div>
        )}
      </div>

      <div className="border-ax-border flex items-center justify-between gap-2 border-t pt-2">
        {modelName ? (
          <p className="text-ax-text-secondary text-[10px]">
            {t("context_usage_model_label")}: <span className="text-ax-text">{modelName}</span>
          </p>
        ) : (
          <span />
        )}
        {/* Only a pinned meter can be hidden here: from SHOW_FROM_PERCENT it
            stays, as the warning it is. */}
        {pinned && !warranted ? (
          <Button
            label={t("context_usage_menu_hide")}
            variant="ghost"
            size="sm"
            icon={<EyeOff className="size-3" aria-hidden />}
            onClick={() => {
              setOpen(false);
              setContextUsagePinned(false);
            }}
          />
        ) : (
          <span />
        )}
      </div>
    </div>
  );

  return (
    <Popover
      isOpen={open}
      onOpenChange={setOpen}
      placement="above"
      alignment="end"
      width={340}
      label={t("context_usage_estimate")}
      closeButtonLabel={t("close")}
      content={details}
    >
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        className="text-ax-text-secondary hover:text-ax-text focus-visible:outline-ring rounded-ax-inner flex min-h-6 w-full items-center gap-3 px-1 text-[11px] leading-none transition-colors focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <span className="sr-only">{t("context_usage")}: </span>
        <div
          aria-hidden="true"
          className="bg-ax-muted border-ax-border relative h-1.5 flex-1 overflow-hidden rounded-full border"
        >
          {segments.map((seg) =>
            seg.widthPct > 0 ? (
              <div
                key={seg.key}
                className={cn(
                  "absolute top-0 bottom-0 my-auto h-[calc(100%-2px)] rounded-full transition-all duration-300 ease-out",
                  segmentClass(seg.key)
                )}
                style={{
                  left: `${seg.leftPct}%`,
                  width: `max(3px, calc(${seg.widthPct}% - 2px))`,
                  marginLeft: "1px"
                }}
              />
            ) : null
          )}
        </div>
        <span
          className={cn(
            "flex items-center gap-1.5 whitespace-nowrap tabular-nums",
            willExceed ? "text-ax-error" : "text-ax-text-secondary"
          )}
        >
          {willExceed && <TriangleAlert className="size-3" aria-hidden />}≈ {fmt(projectedTotal)} /{" "}
          {fmt(contextLimit)} ({percentLabel}%)
          <Info className="size-3" aria-hidden />
        </span>
      </button>
    </Popover>
  );
}
