"use client";

import { useTranslations } from "use-intl";
import type { Schema } from "@/lib/api/models";

type Summary = Schema<"FlowCitationSummaryPublic">;

/**
 * What an answer leaned on: the cited sources as the core resolved them,
 * and what is wrong when citations were required but missing, cited
 * sources the step never retrieved, or citations were on without sources.
 * Shown on a step's result and on a review checkpoint, where a correction
 * can leave the citations behind the edited text (`stale_after_edit`).
 */
export function CitationSummary({
  summary,
  heading
}: {
  summary: Summary | null | undefined;
  heading?: string;
}) {
  const t = useTranslations();
  if (!summary || summary.status === "unavailable") return null;
  const names = summary.sources
    .map((source) =>
      [source.display_name ?? t("flow_runs_citation_unnamed"), source.container_label]
        .filter(Boolean)
        .join(" · ")
    )
    .filter(Boolean);
  return (
    <div className="flex flex-col gap-1">
      <p className="text-ax-text text-sm font-medium">
        {heading ?? t("flow_runs_citations_heading")}
      </p>
      {summary.status === "missing_required_citations" ? (
        <p className="text-ax-text text-sm">{t("flow_runs_citations_missing")}</p>
      ) : summary.status === "unknown_citation_ids_present" ? (
        <p className="text-ax-text text-sm">{t("flow_runs_citations_unknown")}</p>
      ) : summary.status === "citations_on_without_sources" ? (
        <p className="text-ax-text text-sm">{t("flow_runs_citations_no_sources")}</p>
      ) : null}
      {names.length > 0 ? (
        <ul className="text-ax-text flex list-disc flex-col gap-0.5 pl-5 text-sm">
          {names.map((name, index) => (
            <li key={index}>{name}</li>
          ))}
        </ul>
      ) : null}
      {summary.sources_truncated ? (
        <p className="text-ax-text-secondary text-xs">{t("flow_runs_citations_truncated")}</p>
      ) : null}
      {summary.stale_after_edit ? (
        <p className="text-ax-text-secondary text-xs">{t("flow_runs_citations_stale")}</p>
      ) : null}
    </div>
  );
}
