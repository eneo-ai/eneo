"use client";

import { Button } from "@astryxdesign/core/Button";
import { useClipboard } from "@astryxdesign/core/hooks";
import { Token } from "@astryxdesign/core/Token";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { saveBlob } from "@/features/chat/side-panel/document-export";
import { toast } from "@/lib/toast";
import type { FlowPublic } from "../flows-api";
import { EvidenceOmissions } from "./run-evidence-counters";
import { RunEvidenceExport } from "./run-evidence-export";
import type { RunStepView } from "./run-progress";
import { isTerminal } from "./run-status";
import { stepTitle } from "./run-steps";
import { RunTraceAttempts } from "./run-trace-attempts";
import { RunTraceProviderCalls } from "./run-trace-provider-calls";
import {
  runEvidenceQueryOptions,
  type EvidenceAccess,
  type RunEvidence,
  type RunSummary
} from "./runs-api";

function Part({ title, children }: { title: string; children: React.ReactNode }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h3 id={headingId} className="text-ax-text text-base font-semibold">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** The content-free diagnostic export the trace carries, to copy or save for support. */
function DebugExport({ evidence, runId }: { evidence: RunEvidence; runId: string }) {
  const t = useTranslations();
  const { copy, isCopied } = useClipboard({ announce: t("flow_run_extras_debug_copied") });
  const debug = evidence.debug_export;
  // Written out when asked for: the export can be large, and a render need not pay for it.
  const text = () => JSON.stringify(debug, null, 2);
  return (
    <div className="flex flex-col items-start gap-2">
      <p className="text-ax-text-secondary text-sm">{t("flow_run_extras_debug_hint")}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          label={isCopied ? t("copied") : t("flow_run_extras_debug_copy")}
          icon={isCopied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          onClick={async () => {
            if (!(await copy(text()))) toast.error(t("chat_copy_failed"));
          }}
        />
        <Button
          label={t("flow_run_extras_debug_download")}
          icon={<Download aria-hidden="true" />}
          onClick={() =>
            saveBlob(
              new Blob([text()], { type: "application/json" }),
              `flow-debug-export-${debug.run.run_id || runId}.json`
            )
          }
        />
      </div>
    </div>
  );
}

function TraceBody({
  flowId,
  runId,
  evidence,
  stepName
}: {
  flowId: string;
  runId: string;
  evidence: RunEvidence;
  stepName: (order: number) => string;
}) {
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-6">
      {evidence.debug_export.security.redaction_applied ? (
        <div className="flex flex-col items-start gap-1">
          <Token size="sm" label={t("flow_run_more_redacted")} />
          <p className="text-ax-text-secondary m-0 text-xs">{t("flow_run_more_redacted_hint")}</p>
        </div>
      ) : null}
      <EvidenceOmissions summary={evidence.debug_export.run.summary} />
      <Part title={t("flow_run_extras_attempts_heading")}>
        <RunTraceAttempts attempts={evidence.step_attempts} stepName={stepName} />
      </Part>
      <Part title={t("flow_run_extras_calls_heading")}>
        <RunTraceProviderCalls
          flowId={flowId}
          runId={runId}
          firstPage={evidence.provider_calls}
          stepName={stepName}
        />
      </Part>
      <Part title={t("flow_run_extras_debug_heading")}>
        <DebugExport evidence={evidence} runId={runId} />
      </Part>
    </div>
  );
}

/**
 * The run's evidence for those the core lets read it: whether credentials
 * in it are masked, every attempt each step made, the calls to AI services
 * page by page, the content-free diagnostic export, and the evidence export
 * as far as the core allows it.
 * `access` is the run detail's `evidence_access`, decided by the run access
 * policy the evidence routes use; until the detail has been read, and for
 * a caller the core would refuse, the section is not offered. The evidence
 * is an audited read, so it loads when asked for (one read serves the
 * knowledge section too).
 */
export function RunTrace({
  flow,
  summary,
  steps,
  access
}: {
  flow: FlowPublic;
  summary: RunSummary;
  steps: readonly RunStepView[];
  access: EvidenceAccess | undefined;
}) {
  const t = useTranslations();
  const headingId = useId();
  const [requested, setRequested] = useState(false);
  const evidence = useQuery({
    ...runEvidenceQueryOptions(flow.id, summary.id, isTerminal(summary.status)),
    enabled: requested
  });

  if (!access?.can_read_evidence) return null;

  const stepName = (order: number) =>
    stepTitle({ order, label: steps.find((step) => step.order === order)?.label ?? "" }, t);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <h2 id={headingId} className="text-ax-text text-lg font-semibold">
        {t("flow_run_extras_trace_heading")}
      </h2>
      <Part title={t("flow_run_extras_export_heading")}>
        <RunEvidenceExport flowId={flow.id} runId={summary.id} access={access} />
      </Part>
      {!requested ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-ax-text-secondary text-sm">{t("flow_run_extras_trace_hint")}</p>
          <Button label={t("flow_run_extras_trace_show")} onClick={() => setRequested(true)} />
        </div>
      ) : evidence.isPending ? (
        <LoadingState rows={3} label={t("flow_run_extras_trace_loading")} />
      ) : evidence.isError ? (
        <ListError
          error={evidence.error}
          title={t("flow_run_extras_trace_failed")}
          onRetry={() => void evidence.refetch()}
          isRetrying={evidence.isFetching}
        />
      ) : (
        <TraceBody
          key={evidence.dataUpdatedAt}
          flowId={flow.id}
          runId={summary.id}
          evidence={evidence.data}
          stepName={stepName}
        />
      )}
    </section>
  );
}
