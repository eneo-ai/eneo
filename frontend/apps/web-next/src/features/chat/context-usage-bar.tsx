"use client";

import { Eye, EyeOff, Info, TriangleAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemo, useSyncExternalStore } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { ContextUsage } from "@/lib/chat/use-preflight";
import { cn } from "@/lib/utils";

const VISIBILITY_STORAGE_KEY = "contextUsageBarVisible";

// localStorage-backed visibility, read via useSyncExternalStore so there's no
// setState-in-effect and no hydration mismatch (server snapshot = visible).
const visibilityListeners = new Set<() => void>();

function subscribeVisibility(callback: () => void) {
  visibilityListeners.add(callback);
  return () => visibilityListeners.delete(callback);
}

function readVisibility() {
  try {
    return window.localStorage.getItem(VISIBILITY_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

function writeVisibility(next: boolean) {
  try {
    window.localStorage.setItem(VISIBILITY_STORAGE_KEY, next ? "true" : "false");
  } catch {
    // Ignore persistence failures (private mode / blocked storage).
  }
  for (const listener of visibilityListeners) listener();
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
  lockedInput: "bg-muted-foreground/70",
  lockedOutput: "bg-chart-3",
  pendingText: "bg-chart-1",
  pendingFiles: "bg-chart-4"
};

/**
 * Context-usage bar ported from the Svelte `ContextUsageBar`: a segmented
 * progress bar above the composer with a detailed popover breaking the estimate
 * into locked (last turn) vs pending (your text/files) tokens, the running
 * conversation total, and an over-limit warning. Advisory only — the provider
 * validates the final payload.
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

  // Persisted show/hide preference; server snapshot defaults to visible.
  const isVisible = useSyncExternalStore(subscribeVisibility, readVisibility, () => true);

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
    if (willExceed && (key === "pendingText" || key === "pendingFiles")) return "bg-destructive";
    return SEGMENT_CLASS[key] ?? "bg-muted-foreground/70";
  }

  if (!hasUsage) return null;

  if (!isVisible) {
    return (
      <div className="flex w-full justify-end px-1 pt-1 pb-3">
        <button
          type="button"
          onClick={() => writeVisibility(true)}
          aria-label={t("context_usage_show_bar")}
          title={t("context_usage_show_bar")}
          className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-[11px] leading-none transition-colors"
        >
          <Eye className="size-3" aria-hidden />
        </button>
      </div>
    );
  }

  const percentLabel = projectedPercent.toFixed(projectedPercent >= 10 ? 0 : 1);

  return (
    <Popover>
      <PopoverTrigger
        aria-label={t("context_usage")}
        className="text-muted-foreground hover:text-foreground flex w-full items-center gap-3 px-1 pt-1 pb-3 text-[11px] leading-none transition-colors"
      >
        <div
          className="bg-muted relative h-2.5 flex-1 overflow-hidden rounded-full border"
          role="progressbar"
          aria-valuenow={projectedTotal}
          aria-valuemin={0}
          aria-valuemax={contextLimit}
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
            willExceed ? "text-destructive" : "text-muted-foreground"
          )}
        >
          {willExceed && <TriangleAlert className="size-3" aria-hidden />}≈ {fmt(projectedTotal)} /{" "}
          {fmt(contextLimit)} ({percentLabel}%)
          <Info className="size-3 opacity-70" aria-hidden />
        </span>
      </PopoverTrigger>

      <PopoverContent side="top" align="end" className="w-[340px] p-0">
        <div className="border-b px-4 py-3">
          <p className="text-sm font-medium">{t("context_usage_estimate")}</p>
          <p className="text-muted-foreground mt-0.5 text-xs tabular-nums">
            ≈ {fmt(projectedTotal)} / {fmt(contextLimit)} {t("chat_tokens_separator")}{" "}
            {percentLabel}%
          </p>
        </div>

        <div className="space-y-3 px-4 py-3 text-xs">
          {(lockedInputTokens > 0 || lockedOutputTokens > 0) && (
            <div className="space-y-1.5">
              <p className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
                {t("context_usage_section_locked")}
              </p>
              <div className="flex items-baseline justify-between gap-3">
                <span className="flex items-center gap-2">
                  <span className="bg-muted-foreground/70 inline-block size-2.5 rounded-full" />
                  {t("context_usage_label_input")}
                </span>
                <span className="text-muted-foreground tabular-nums">{fmt(lockedInputTokens)}</span>
              </div>
              <p className="text-muted-foreground pl-[18px] text-[10px] leading-snug">
                {t("context_usage_label_input_hint")}
              </p>
              <div className="flex items-baseline justify-between gap-3">
                <span className="flex items-center gap-2">
                  <span className="bg-chart-3 inline-block size-2.5 rounded-full" />
                  {t("context_usage_label_output")}
                </span>
                <span className="text-muted-foreground tabular-nums">
                  {fmt(lockedOutputTokens)}
                </span>
              </div>
            </div>
          )}

          {pendingTotal > 0 && (
            <div className="space-y-1.5 border-t pt-3">
              <p className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
                {t("context_usage_section_pending")}
              </p>
              {pendingTextTokens > 0 && (
                <div className="flex items-baseline justify-between gap-3">
                  <span className="flex items-center gap-2">
                    <span className="bg-chart-1 inline-block size-2.5 rounded-full" />
                    {t("context_usage_label_your_text")}
                  </span>
                  <span className="text-muted-foreground tabular-nums">
                    {fmt(pendingTextTokens)}
                  </span>
                </div>
              )}
              {pendingFileTokens > 0 && (
                <div className="flex items-baseline justify-between gap-3">
                  <span className="flex items-center gap-2">
                    <span className="bg-chart-4 inline-block size-2.5 rounded-full" />
                    {t("context_usage_label_files")}
                  </span>
                  <span className="text-muted-foreground tabular-nums">
                    {fmt(pendingFileTokens)}
                  </span>
                </div>
              )}
            </div>
          )}

          {pendingTotal > 0 && (
            <div className="space-y-1.5 border-t pt-3">
              <p className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
                {t("context_usage_section_excluded")}
              </p>
              <p className="text-muted-foreground leading-snug">
                {t("context_usage_excluded_hint")}
              </p>
            </div>
          )}

          {hasCumulative && (
            <div className="space-y-1.5 border-t pt-3">
              <p className="text-muted-foreground text-[10px] font-medium tracking-wide uppercase">
                {t("context_usage_section_cumulative")}
              </p>
              <div className="flex items-baseline justify-between gap-3">
                <span>{t("context_usage_cumulative_label")}</span>
                <span className="text-muted-foreground tabular-nums">{cumulativeSummary}</span>
              </div>
              {turnCount > 1 && (
                <p className="text-muted-foreground text-[10px] leading-snug tabular-nums">
                  {t("context_usage_cumulative_average", { average: fmt(averagePerTurn) })}
                </p>
              )}
              <p className="text-muted-foreground leading-snug">
                {t("context_usage_cumulative_hint")}
              </p>
            </div>
          )}

          {willExceed && (
            <div className="bg-destructive/10 text-destructive flex flex-col gap-2 rounded-md px-2 py-1.5">
              <div className="flex items-start gap-2">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span className="text-[11px] leading-snug">
                  {t("context_usage_will_exceed_estimate")}
                </span>
              </div>
              {onNewConversation && (
                <button
                  type="button"
                  onClick={onNewConversation}
                  className="border-destructive/40 hover:bg-destructive/10 self-start rounded-md border px-2 py-1 text-[11px] font-medium transition-colors"
                >
                  {t("new_conversation")}
                </button>
              )}
            </div>
          )}
        </div>

        <div className="bg-muted/40 flex items-center justify-between gap-2 border-t px-4 py-2">
          {modelName ? (
            <p className="text-muted-foreground text-[10px]">
              {t("context_usage_model_label")}: <span className="text-foreground">{modelName}</span>
            </p>
          ) : (
            <span />
          )}
          <button
            type="button"
            onClick={() => writeVisibility(false)}
            className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-[10px] transition-colors"
          >
            <EyeOff className="size-3" aria-hidden />
            {t("context_usage_hide_bar")}
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
