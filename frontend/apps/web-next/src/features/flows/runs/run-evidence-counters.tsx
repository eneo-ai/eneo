"use client";

import { useTranslations } from "use-intl";
import type { Schema } from "@/lib/api/models";

type Summary = Schema<"FlowRunDebugRunSummary">;
type KnowledgeView = Schema<"FlowRunDebugKnowledgeEvidenceView">;
type Omission = NonNullable<Summary["omissions"]>[number];

/** A count the core may have stopped at: "≥ n" when it did. */
function counted(count: number, truncated: boolean | null | undefined): string {
  return `${truncated ? "≥" : ""}${count}`;
}

function OmissionLine({ omission }: { omission: Omission }) {
  const t = useTranslations();
  const values = {
    section: t(`flow_run_evidence_section_${omission.section}`),
    count: counted(omission.rows_omitted, omission.count_truncated)
  };
  switch (omission.reason) {
    case "logical_bytes":
      return <li>{t("flow_run_evidence_view_bytes_omitted", values)}</li>;
    case "parent_section_omitted":
      return <li>{t("flow_run_evidence_view_parent_omitted", values)}</li>;
    default:
      return <li>{t("flow_run_evidence_view_rows_omitted", values)}</li>;
  }
}

/**
 * What the evidence view left out, per section and why (too many rows,
 * too many bytes, or the rows they belong to were left out), with how many:
 * all of it is still stored and goes into an export.
 */
export function EvidenceOmissions({ summary }: { summary: Summary | null | undefined }) {
  const omissions = summary?.omissions ?? [];
  if (omissions.length === 0) return null;
  return (
    <ul className="text-ax-text-secondary m-0 flex list-disc flex-col gap-1 pl-5 text-sm">
      {omissions.map((omission) => (
        <OmissionLine key={`${omission.section}-${omission.reason}`} omission={omission} />
      ))}
    </ul>
  );
}

/**
 * What the knowledge part of the evidence view left out: passages kept
 * out of view, attempts not read in, attempts whose passage sizes cannot be
 * read, and steps whose search could not be read within the view's bounds
 * (so an empty list for them does not mean nothing was found).
 */
export function KnowledgeViewCounters({ view }: { view: KnowledgeView | null | undefined }) {
  const t = useTranslations();
  if (!view) return null;
  const truncated = view.count_truncated;
  const lines = [
    view.passages_omitted > 0
      ? t("flow_run_knowledge_view_omitted_passages", { omitted: view.passages_omitted })
      : null,
    (view.attempts_not_loaded ?? 0) > 0
      ? t("flow_run_knowledge_view_attempts_not_loaded", {
          count: counted(view.attempts_not_loaded ?? 0, truncated)
        })
      : null,
    (view.corrupt_passage_aggregates ?? 0) > 0
      ? t("flow_run_knowledge_view_corrupt_passage_aggregates", {
          count: counted(view.corrupt_passage_aggregates ?? 0, truncated)
        })
      : null,
    (view.current_attempts_not_loaded ?? 0) > 0
      ? t("flow_run_knowledge_view_current_attempts_not_loaded", {
          count: counted(view.current_attempts_not_loaded ?? 0, truncated),
          steps: (view.current_step_orders_not_loaded ?? []).join(", ")
        })
      : null
  ].filter((line): line is string => line !== null);
  if (lines.length === 0) return null;
  return (
    <ul className="text-ax-text-secondary m-0 flex list-disc flex-col gap-1 pl-5 text-sm">
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}
