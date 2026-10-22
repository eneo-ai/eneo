"use client";

import { Button } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import type { Schema } from "@/lib/api/models";
import { formatCount } from "./run-format";
import { stepTitle } from "./run-steps";
import type { RunStepView } from "./run-progress";
import { runEvidenceQueryOptions } from "./runs-api";

type Rag = Schema<"FlowRunDebugRag">;
type Reference = Schema<"FlowRunDebugRagReference">;

/** The references a step's retrieval recorded, from the trace and any nested mapped calls. */
export function traceReferences(rag: Rag): Reference[] {
  const nested = [...(rag.items ?? []), ...(rag.sources ?? [])].flatMap(traceReferences);
  return [...(rag.references ?? []), ...nested];
}

function referenceName(reference: Reference, fallback: string): string {
  return (
    reference.source_display_name?.trim() ||
    reference.source_title?.trim() ||
    reference.display_title?.trim() ||
    reference.title?.trim() ||
    fallback
  );
}

function ReferenceRow({ reference }: { reference: Reference }) {
  const t = useTranslations();
  const locale = useLocale();
  const container =
    reference.source_container_display_name?.trim() || reference.source_container_label?.trim();
  const withheld = (reference.passages ?? []).filter(
    (passage) => (passage.disclosure ?? "text_disclosed") !== "text_disclosed"
  ).length;
  return (
    <li className="border-ax-border flex flex-col gap-1 border-t py-2 first:border-t-0">
      <span className="text-ax-text text-sm font-medium break-words">
        {referenceName(reference, t("flow_runs_citation_unnamed"))}
        {container ? (
          <span className="text-ax-text-secondary font-normal"> · {container}</span>
        ) : null}
      </span>
      <span className="text-ax-text-secondary text-xs">
        {[
          t("flow_runs_knowledge_matches", {
            count: formatCount(Math.max(0, reference.matched_chunk_count), locale)
          }),
          reference.usage_state === "inserted_into_prompt"
            ? t("flow_runs_knowledge_used")
            : t("flow_runs_knowledge_candidate")
        ].join(" · ")}
      </span>
      {reference.display_snippet ? (
        <span className="text-ax-text text-sm break-words">{reference.display_snippet}</span>
      ) : null}
      {withheld > 0 ? (
        <span className="text-ax-text-secondary text-xs">
          {t("flow_runs_knowledge_withheld", { count: withheld })}
        </span>
      ) : null}
    </li>
  );
}

/**
 * What the run's steps found in their knowledge: per step, each source a
 * search matched, how many passages it matched, whether they went into the
 * prompt, and the text the evidence policy lets this reader see. The
 * evidence is an audited read, so it loads when asked for.
 */
export function RunKnowledge({
  flowId,
  runId,
  steps
}: {
  flowId: string;
  runId: string;
  steps: readonly RunStepView[];
}) {
  const t = useTranslations();
  const [requested, setRequested] = useState(false);
  const evidence = useQuery({ ...runEvidenceQueryOptions(flowId, runId), enabled: requested });

  if (!requested) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-ax-text-secondary text-sm">{t("flow_runs_knowledge_hint")}</p>
        <Button label={t("flow_runs_knowledge_show")} onClick={() => setRequested(true)} />
      </div>
    );
  }
  if (evidence.isPending) return <LoadingState rows={2} label={t("flow_runs_knowledge_loading")} />;
  if (evidence.isError) {
    return (
      <ListError
        error={evidence.error}
        title={t("flow_runs_knowledge_failed")}
        onRetry={() => void evidence.refetch()}
        isRetrying={evidence.isFetching}
      />
    );
  }
  const traces = (evidence.data.knowledge_traces ?? [])
    .map((trace) => ({ trace, references: traceReferences(trace.rag) }))
    .filter(({ trace, references }) => references.length > 0 || trace.rag.attempted);
  if (traces.length === 0) {
    return <p className="text-ax-text-secondary text-sm">{t("flow_runs_knowledge_none")}</p>;
  }
  return (
    <div className="flex flex-col gap-4">
      {traces.map(({ trace, references }) => {
        const step = steps.find((candidate) => candidate.order === trace.step_order);
        return (
          <section key={trace.step_order} className="flex flex-col gap-1">
            <h3 className="text-ax-text text-base font-semibold">
              {stepTitle({ order: trace.step_order, label: step?.label ?? "" }, t)}
            </h3>
            {trace.rag.error_code ? (
              <p className="text-ax-text text-sm">{t("flow_runs_knowledge_search_failed")}</p>
            ) : null}
            {references.length === 0 ? (
              <p className="text-ax-text-secondary text-sm">
                {t("flow_runs_knowledge_nothing_found")}
              </p>
            ) : (
              <ul className="m-0 flex flex-col p-0">
                {references.map((reference, index) => (
                  <ReferenceRow key={`${reference.id}-${index}`} reference={reference} />
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
