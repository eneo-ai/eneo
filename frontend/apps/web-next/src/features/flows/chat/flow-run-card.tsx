"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce, useClipboard } from "@astryxdesign/core/hooks";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Check, CircleAlert, Copy, Play } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { IconTile } from "@/components/composites/icon-tile";
import { StatusLabel } from "@/components/composites/status-label";
import { browserApi } from "@/lib/api/browser";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import { isFlowsToolCall } from "./flows-tool-call";
import { CancelRunButton } from "../runs/run-actions";
import { RunFailure } from "../runs/run-failure";
import { formatSeconds } from "../runs/run-format";
import { RunLiveProgress } from "../runs/run-live-progress";
import { progressSignature, runStepViews, tokenTotal } from "../runs/run-progress";
import { runHref } from "../runs/run-routes";
import {
  createPollClock,
  isCancellable,
  isTerminal,
  runDurationMs,
  runStatusView,
  shouldPoll,
  stepStatusView
} from "../runs/run-status";
import { stepTitle } from "../runs/run-steps";
import { RunText } from "../runs/run-text";
import {
  getRunGraph,
  getRunStatus,
  runDetailQueryOptions,
  runKeys,
  type RunDetail
} from "../runs/runs-api";

/** The tool of the flow chat that starts a run. */
const RUN_FLOW_TOOL = "run_flow";

/** The run a `run_flow` call of the flow chat started, from the call's data; null for any other call. */
export function startedRunId(
  call: Pick<ToolCallRecord, "toolName" | "structuredContent" | "serverName" | "isInternal">
): string | null {
  if (!isFlowsToolCall(call) || call.toolName !== RUN_FLOW_TOOL) return null;
  const runId = call.structuredContent?.run_id;
  return typeof runId === "string" && runId ? runId : null;
}

/** The chat's card for a tool call: the run card for a run `run_flow` started, nothing for other calls. */
export function flowRunCardFor(
  call: ToolCallRecord,
  flow: { id: string; name: string },
  spaceRouteId: string,
  onAskChat?: (text: string) => void
): ReactNode {
  const runId = startedRunId(call);
  if (!runId) return null;
  return (
    <FlowRunCard
      flowId={flow.id}
      flowName={flow.name}
      runId={runId}
      spaceRouteId={spaceRouteId}
      onAskChat={onAskChat}
    />
  );
}

/** The result of a completed run as text, when it has one; null for files and structured values. */
function resultText(run: RunDetail | undefined): string | null {
  const result = run?.result;
  if (!result) return null;
  if (result.kind === "inline_text") return result.text;
  if (result.kind === "file_backed_text") return result.preview;
  return null;
}

/**
 * A run the flow chat started, drawn in the answer where it was started:
 * what it is doing step by step while it runs (read the way the run page
 * reads it, so the model does not have to wait for it), the result when it
 * is done, why it failed when it did, and the way to the run's own page.
 * Reopening the conversation shows the run as it ended. Once the run has
 * ended, "Förklara felet" and "Förbättra utifrån körningen" put a prepared
 * request about this run in the composer (`onAskChat`), never send it.
 */
export function FlowRunCard({
  flowId,
  flowName,
  runId,
  spaceRouteId,
  onAskChat
}: {
  flowId: string;
  flowName: string;
  runId: string;
  spaceRouteId: string;
  onAskChat?: (text: string) => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const { copy } = useClipboard({ announce: t("copied_to_clipboard") });
  const [clock] = useState(() => createPollClock());
  const lastStatus = useRef<string | null>(null);

  // The content-free status and graph, polled while the run moves (the
  // same query as the run page, so the two never read twice).
  const progress = useQuery({
    queryKey: runKeys.progress(flowId, runId),
    queryFn: async ({ signal }) => {
      const [status, graph] = await Promise.all([
        getRunStatus(flowId, runId, signal),
        getRunGraph(flowId, runId, signal)
      ]);
      return { status, graph };
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      return clock(progressSignature(data.status, data.graph), shouldPoll(data.status.status));
    },
    refetchIntervalInBackground: false
  });
  const summary = progress.data?.status;
  const status = summary?.status ?? null;
  const settled = status ? isTerminal(status) : false;
  const signature = progress.data
    ? progressSignature(progress.data.status, progress.data.graph)
    : null;
  // The audited detail (the result, the error, what it used): read once the
  // run has ended, and again only if it moved.
  const detail = useQuery({
    ...runDetailQueryOptions(browserApi, flowId, runId, signature ?? ""),
    enabled: signature !== null && settled,
    placeholderData: keepPreviousData
  });
  const steps = progress.data ? runStepViews(progress.data.graph, null) : [];

  useEffect(() => {
    if (status && lastStatus.current && lastStatus.current !== status) {
      announce(t("flow_runs_status_now", { status: t(runStatusView(status).labelKey) }));
    }
    lastStatus.current = status;
  }, [announce, status, t]);

  const href = runHref(spaceRouteId, flowId, runId);
  const label = t("flows_run_card_title", { flow: flowName });
  const view = status ? runStatusView(status) : null;
  const text = status === "completed" ? resultText(detail.data) : null;
  const tokens = tokenTotal(
    detail.data?.token_usage?.num_tokens_input,
    detail.data?.token_usage?.num_tokens_output
  );
  const duration = summary ? runDurationMs(summary) : null;
  const facts = [
    summary ? t("flow_runs_version", { version: summary.flow_version }) : null,
    steps.length > 0 && settled ? t("flows_run_card_steps", { count: steps.length }) : null,
    duration !== null ? formatSeconds(duration / 1000, t) : null,
    tokens !== null ? t("flow_runs_tokens", { count: tokens }) : null
  ].filter((fact): fact is string => fact !== null);

  return (
    <section
      aria-label={label}
      className="border-ax-border bg-ax-sunken rounded-ax-container flex w-full flex-col gap-3 border p-3.5 font-sans"
    >
      <div className="flex items-center gap-2.5">
        <IconTile
          size="sm"
          hue={status === "completed" ? "teal" : status === "failed" ? "pink" : "blue"}
          icon={
            status === "completed" ? (
              <Check className="size-4" />
            ) : status === "failed" ? (
              <CircleAlert className="size-4" />
            ) : (
              <Play className="size-4" />
            )
          }
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <h3 className="m-0 text-[13.5px] font-semibold">{label}</h3>
          {facts.length > 0 ? (
            <p className="text-ax-text-secondary m-0 text-xs">{facts.join(" · ")}</p>
          ) : null}
        </div>
        {view ? (
          <StatusLabel
            status={view.tone}
            label={t(view.labelKey)}
            isPulsing={view.isPulsing}
            className="text-ax-text text-[13px] font-semibold"
          />
        ) : null}
      </div>

      {progress.isError ? (
        <p className="text-ax-error m-0 text-sm">{t("flows_run_card_unavailable")}</p>
      ) : null}

      {summary && !settled ? (
        <>
          <RunLiveProgress summary={summary} steps={steps} />
          {steps.length > 0 ? (
            <ol className="m-0 flex list-none flex-col gap-1 p-0">
              {steps.map((step) => {
                const stepView = stepStatusView(step.status);
                return (
                  <li key={step.order} className="flex items-center gap-2 text-sm">
                    <StatusLabel
                      status={stepView.tone}
                      label={stepTitle(step, t)}
                      isPulsing={stepView.isPulsing}
                      className={cn("text-ax-text", step.status === "running" && "font-semibold")}
                    />
                    <span className="flex-1" />
                    <span className="text-ax-text-secondary text-xs">{t(stepView.labelKey)}</span>
                  </li>
                );
              })}
            </ol>
          ) : null}
        </>
      ) : null}

      {status === "completed" && detail.data ? (
        text ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-ax-text-secondary m-0 text-xs font-semibold">
              {t("flows_run_card_result")}
            </p>
            <div className="border-ax-border bg-ax-surface rounded-ax-element line-clamp-[8] border px-3 py-2">
              <RunText text={text} />
            </div>
          </div>
        ) : (
          <p className="text-ax-text-secondary m-0 text-sm">
            {t("flows_run_card_result_elsewhere")}
          </p>
        )
      ) : null}

      {status === "failed" && detail.data?.error ? (
        <RunFailure
          error={detail.data.error}
          stepName={(order) => steps.find((step) => step.order === order)?.label ?? null}
        />
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          href={href}
          size="sm"
          label={settled ? t("flows_run_card_show_run") : t("flows_run_card_open_run")}
        />
        {text ? (
          <Button
            size="sm"
            variant="ghost"
            label={t("copy")}
            icon={<Copy aria-hidden="true" className="size-4" />}
            onClick={() => void copy(text)}
          />
        ) : null}
        {onAskChat && status === "failed" ? (
          <Button
            size="sm"
            variant="ghost"
            label={t("flows_run_card_explain")}
            onClick={() => onAskChat(t("flows_run_card_explain_request", { run: runId }))}
          />
        ) : null}
        {onAskChat && (status === "completed" || status === "failed") ? (
          <Button
            size="sm"
            variant="ghost"
            label={t("flows_run_card_improve")}
            onClick={() => onAskChat(t("flows_run_card_improve_request", { run: runId }))}
          />
        ) : null}
        {status && isCancellable(status) ? (
          <CancelRunButton
            flowId={flowId}
            runId={runId}
            size="sm"
            report={(notice) =>
              notice.status === "error"
                ? toast.error(notice.title, { description: notice.description })
                : toast.info(notice.title, { description: notice.description })
            }
            onCancelled={() => undefined}
          />
        ) : null}
      </div>
    </section>
  );
}
