"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Token } from "@astryxdesign/core/Token";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { TextInput } from "@astryxdesign/core/TextInput";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import type { Schema } from "@/lib/api/models";
import { relevanceLevel } from "./run-chunk-highlight";
import { KnowledgeViewCounters } from "./run-evidence-counters";
import { formatCount } from "./run-format";
import { KnowledgeSourceViewer } from "./run-knowledge-source";
import {
  filterTraceSources,
  knowledgeStatusView,
  mappedCallsIncomplete,
  passageDetailNote,
  relevancePercent,
  showsKnowledgeTrace,
  traceSourceTotal,
  traceSources,
  traceSummary,
  type TraceSource
} from "./run-knowledge-trace";
import { stepTitle } from "./run-steps";
import type { RunStepView } from "./run-progress";
import { runEvidenceQueryOptions } from "./runs-api";

type Rag = Schema<"FlowRunDebugRag">;
type Reference = Schema<"FlowRunDebugRagReference">;

/** Sources listed under a step before "Visa alla källor". */
const INLINE_SOURCES = 4;
/** Sources the all-sources dialog lists at once; the search narrows the rest. */
const DIALOG_SOURCES = 50;

const RELEVANCE_COLOR = { high: "green", moderate: "yellow", low: "default" } as const;

function referenceName(reference: Reference, fallback: string): string {
  return (
    reference.source_display_name?.trim() ||
    reference.source_title?.trim() ||
    reference.display_title?.trim() ||
    reference.title?.trim() ||
    fallback
  );
}

/**
 * One source a search found: its name and container, how many passages it
 * matched and whether they went into the prompt, how relevant its best
 * passage was (level and percent), the mapped call it came from, whether
 * its text is withheld from this reader, and its snippet. It opens in the
 * source viewer.
 */
function SourceRow({ source }: { source: TraceSource }) {
  const t = useTranslations();
  const locale = useLocale();
  const [viewing, setViewing] = useState(false);
  const { reference, callNumber } = source;
  const name = referenceName(reference, t("flow_runs_citation_unnamed"));
  const container =
    reference.source_container_display_name?.trim() || reference.source_container_label?.trim();
  const withheld = (reference.passages ?? []).some(
    (passage) => (passage.disclosure ?? "text_disclosed") !== "text_disclosed"
  );
  const level = relevanceLevel(Number(reference.best_score ?? 0));
  return (
    <li className="border-ax-border flex flex-col gap-1 border-t py-2 first:border-t-0">
      <span className="flex flex-wrap items-start justify-between gap-2">
        <span className="text-ax-text text-sm font-medium break-words">
          {name}
          {container ? (
            <span className="text-ax-text-secondary font-normal"> · {container}</span>
          ) : null}
        </span>
        <Button
          label={t("flow_run_journey_source_show")}
          aria-label={t("flow_run_journey_source_show_named", { name })}
          size="sm"
          onClick={() => setViewing(true)}
        />
      </span>
      <KnowledgeSourceViewer
        reference={reference}
        name={name}
        open={viewing}
        onOpenChange={setViewing}
      />
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
      <span className="flex flex-wrap gap-1">
        <Token
          size="sm"
          color={RELEVANCE_COLOR[level]}
          label={t("flow_run_ktrace_relevance", {
            level: t(`flow_run_knowledge_relevance_${level}`),
            percent: relevancePercent(reference.best_score)
          })}
        />
        {callNumber !== null ? (
          <Token
            size="sm"
            label={t("flow_run_knowledge_mapped_call_badge", { call: callNumber })}
          />
        ) : null}
        {withheld ? (
          <Token size="sm" label={t("flow_run_knowledge_passages_withheld_badge")} />
        ) : null}
      </span>
      {reference.display_snippet ? (
        <span className="text-ax-text text-sm break-words">{reference.display_snippet}</span>
      ) : null}
    </li>
  );
}

function SourceList({ sources }: { sources: readonly TraceSource[] }) {
  return (
    <ul className="m-0 flex flex-col p-0">
      {sources.map((source) => (
        <SourceRow key={source.key} source={source} />
      ))}
    </ul>
  );
}

/** Every source a step found, searchable by name, container, address or id. */
function AllSourcesDialog({
  sources,
  stepName,
  open,
  onOpenChange
}: {
  sources: readonly TraceSource[];
  stepName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const [query, setQuery] = useState("");
  const matching = filterTraceSources(sources, query);
  const shown = matching.slice(0, DIALOG_SOURCES);
  return (
    <Dialog isOpen={open} onOpenChange={onOpenChange} width={880} maxHeight="86dvh">
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={t("flow_run_knowledge_all_sources_title")}
            subtitle={t("flow_run_ktrace_all_sources_subtitle", {
              step: stepName,
              count: sources.length
            })}
            onOpenChange={onOpenChange}
          />
        }
        content={
          open ? (
            <LayoutContent>
              <div className="flex flex-col gap-3">
                <TextInput
                  label={t("flow_run_ktrace_search_sources")}
                  size="sm"
                  startIcon={Search}
                  value={query}
                  onChange={setQuery}
                  hasClear
                />
                <p className="text-ax-text-secondary m-0 text-xs">
                  {t("flow_run_knowledge_filter_sources_summary", {
                    shown: shown.length,
                    total: matching.length
                  })}
                </p>
                {matching.length === 0 ? (
                  <p className="text-ax-text-secondary m-0 text-sm">
                    {t("flow_run_knowledge_no_matching_sources")}
                  </p>
                ) : (
                  <SourceList sources={shown} />
                )}
                {shown.length < matching.length ? (
                  <p className="text-ax-text-secondary m-0 text-sm">
                    {t("flow_run_knowledge_filter_sources_limit_hint", {
                      shown: shown.length,
                      total: matching.length
                    })}
                  </p>
                ) : null}
              </div>
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex justify-end">
                <Button label={t("done")} variant="primary" onClick={() => onOpenChange(false)} />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}

/**
 * One step's knowledge search: how it went (done, nothing found, too slow,
 * failed with its error type, or skipped and why), how many sources and
 * passages it found and how long it took, and the first sources, with
 * "Visa alla källor" for the rest. A mapped step that stopped before all
 * its calls ran says that the trace covers only the calls that finished.
 */
function StepKnowledgeTrace({
  rag,
  sources,
  title
}: {
  rag: Rag;
  sources: readonly TraceSource[];
  title: string;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const headingId = useId();
  const [showAll, setShowAll] = useState(false);
  const summary = traceSummary(rag);
  const status = knowledgeStatusView(summary.status);
  const note = passageDetailNote(rag, sources.length);
  const facts = [
    t("flow_run_ktrace_sources", {
      count: formatCount(traceSourceTotal(rag, sources.length), locale)
    }),
    t("flow_run_ktrace_passages", { count: formatCount(summary.chunks, locale) }),
    summary.durationMs !== null
      ? t("flow_run_ktrace_latency", {
          time: new Intl.NumberFormat(locale, {
            style: "unit",
            unit: "millisecond",
            unitDisplay: "short"
          }).format(summary.durationMs)
        })
      : null
  ].filter(Boolean);
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h3 id={headingId} className="text-ax-text text-base font-semibold">
        {title}
      </h3>
      <StatusLabel status={status.tone} label={t(status.key)} />
      <p className="text-ax-text-secondary m-0 text-sm">{facts.join(" · ")}</p>
      {summary.errorType ? (
        <p className="text-ax-text-secondary m-0 text-xs">
          {t("flow_run_knowledge_error_type")}:{" "}
          <code className="font-mono">{summary.errorType}</code>
        </p>
      ) : rag.error_code && status.tone !== "error" ? (
        <p className="text-ax-text m-0 text-sm">{t("flow_runs_knowledge_search_failed")}</p>
      ) : null}
      {mappedCallsIncomplete(rag) ? (
        <Banner
          status="warning"
          title={t("flow_run_knowledge_mapped_fan_out_incomplete")}
          collapsible={false}
        />
      ) : null}
      {sources.length === 0 ? (
        // A skipped search found nothing because it did not search; its status says why.
        summary.status?.startsWith("skipped") ? null : (
          <p className="text-ax-text-secondary m-0 text-sm">
            {t("flow_runs_knowledge_nothing_found")}
          </p>
        )
      ) : (
        <>
          <SourceList sources={sources.slice(0, INLINE_SOURCES)} />
          {sources.length > INLINE_SOURCES ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-ax-text-secondary m-0 text-xs">
                {t("flow_run_knowledge_inline_sources_summary", {
                  shown: INLINE_SOURCES,
                  total: sources.length
                })}
              </p>
              <Button
                label={t("flow_run_knowledge_show_all_sources", { count: sources.length })}
                size="sm"
                onClick={() => setShowAll(true)}
              />
              <AllSourcesDialog
                sources={sources}
                stepName={title}
                open={showAll}
                onOpenChange={setShowAll}
              />
            </div>
          ) : null}
        </>
      )}
      {note ? (
        <p className="text-ax-text-secondary m-0 text-xs">
          {note.kind === "withheld"
            ? t("flow_run_knowledge_passages_withheld", { count: note.count })
            : t("flow_run_knowledge_passage_detail_partial", {
                detailed: note.detailed,
                total: note.total
              })}
        </p>
      ) : null}
    </section>
  );
}

/**
 * What the run's steps found in their knowledge: per step how the search
 * went, how long it took and what it found, each source with how relevant
 * it was and the mapped call it came from, searchable when there are many;
 * each source opens in a viewer with its passages highlighted. What the
 * evidence view left out is counted. The evidence is an audited read, so it
 * loads when asked for.
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
  const counters = (
    <KnowledgeViewCounters view={evidence.data.debug_export.run.summary?.knowledge_evidence_view} />
  );
  const traces = (evidence.data.knowledge_traces ?? [])
    .map((trace) => ({ trace, sources: traceSources(trace.rag) }))
    .filter(({ trace, sources }) => showsKnowledgeTrace(traceSummary(trace.rag), sources.length));
  if (traces.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        {counters}
        <p className="text-ax-text-secondary text-sm">{t("flow_runs_knowledge_none")}</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      {counters}
      {traces.map(({ trace, sources }) => {
        const step = steps.find((candidate) => candidate.order === trace.step_order);
        return (
          <StepKnowledgeTrace
            key={trace.step_order}
            rag={trace.rag}
            sources={sources}
            title={stepTitle({ order: trace.step_order, label: step?.label ?? "" }, t)}
          />
        );
      })}
    </div>
  );
}
