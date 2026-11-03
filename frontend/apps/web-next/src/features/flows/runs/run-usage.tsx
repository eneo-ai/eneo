import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { useLocale, useTranslations } from "use-intl";
import { formatCount, formatSeconds } from "./run-format";
import { tokenTotal } from "./run-progress";
import type { RunListItem } from "./runs-api";

/** The same provider measurements in run detail and the history table. */
export function RunUsage({ run, compact = false }: { run: RunListItem; compact?: boolean }) {
  const t = useTranslations();
  const locale = useLocale();
  const tokens = run.token_usage;
  const audio = run.transcription_usage;
  if (!tokens && !audio)
    return compact ? (
      <span className="text-ax-text-secondary">{t("flow_runs_usage_not_recorded")}</span>
    ) : null;
  const total = tokens ? tokenTotal(tokens.num_tokens_input, tokens.num_tokens_output) : null;
  const list = (
    <MetadataList columns={compact ? "single" : "multi"}>
      {tokens && total !== null ? (
        <MetadataListItem label={t("flow_runs_usage_tokens")}>
          {t("flow_runs_usage_tokens_value", {
            total: formatCount(total, locale),
            input: formatCount(tokens.num_tokens_input, locale),
            output: formatCount(tokens.num_tokens_output, locale)
          })}
          {tokens.input_completeness === "incomplete" || tokens.output_completeness === "incomplete"
            ? ` ${t("flow_runs_usage_incomplete")}`
            : ""}
        </MetadataListItem>
      ) : null}
      {audio ? (
        <MetadataListItem label={t("flow_runs_usage_audio")}>
          {formatSeconds(audio.audio_seconds, t)}
          {audio.completeness === "incomplete" ? ` ${t("flow_runs_usage_incomplete")}` : ""}
        </MetadataListItem>
      ) : null}
    </MetadataList>
  );
  if (compact || !tokens || total === null) return list;
  return (
    <div className="flex flex-col gap-2">
      {list}
      <p className="text-ax-text-secondary m-0 max-w-prose text-xs">
        {t("flow_runs_usage_tokens_explainer")}
      </p>
    </div>
  );
}

/**
 * What a run used, in a few words for its status line: its tokens and the
 * audio it transcribed, each marked when a count is missing. The usage
 * section has the split and what tokens are.
 */
export function RunUsageBrief({ run }: { run: RunListItem }) {
  const t = useTranslations();
  const locale = useLocale();
  const tokens = run.token_usage;
  const audio = run.transcription_usage;
  const total = tokens ? tokenTotal(tokens.num_tokens_input, tokens.num_tokens_output) : null;
  const incomplete = ` ${t("flow_runs_usage_incomplete")}`;
  return (
    <>
      {tokens && total !== null ? (
        <span className="text-ax-text-secondary">
          {t("flow_run_summary_tokens", { total: formatCount(total, locale) })}
          {tokens.input_completeness === "incomplete" || tokens.output_completeness === "incomplete"
            ? incomplete
            : ""}
        </span>
      ) : null}
      {audio ? (
        <span className="text-ax-text-secondary">
          {t("flow_run_summary_audio", { duration: formatSeconds(audio.audio_seconds, t) })}
          {audio.completeness === "incomplete" ? incomplete : ""}
        </span>
      ) : null}
    </>
  );
}
