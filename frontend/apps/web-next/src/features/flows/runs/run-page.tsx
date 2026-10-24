"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseQuery
} from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { ListError } from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { useFocusRescue } from "@/lib/focus-rescue";
import { CopyableValue } from "@/features/chat/debug-section";
import { useSpaceDisplayName, useSpaceSections } from "@/features/spaces/frame/space-header";
import { spaceLandingHref } from "@/features/spaces/frame/space-sections";
import { useSpace } from "@/features/spaces/use-space";
import { formFieldsOf } from "../flow-form-fields";
import { flowQueryOptions, type FlowPublic } from "../flows-api";
import { formatCount, formatSeconds } from "./run-format";
import { RunFailure } from "./run-failure";
import { RunWebhookDeliveries } from "./run-webhooks";
import { RunFiles } from "./run-files";
import { JsonValue } from "./run-json";
import { refusalText, runErrorText } from "./run-messages";
import { progressSignature, runStepViews, tokenTotal, type RunStepView } from "./run-progress";
import { RunLiveProgress } from "./run-live-progress";
import { RunKnowledge } from "./run-knowledge";
import { starterName } from "./run-starter";
import { RunSteps, stepTitle } from "./run-steps";
import { RunText } from "./run-text";
import { RunTrace } from "./run-trace";
import { RunTranscripts } from "./run-transcript";
import { reviewTranscriptTarget, transcriptTargets } from "./transcript";
import { reviewDraftOf } from "./review-draft";
import {
  canRedispatch,
  createPollClock,
  isAwaitingReview,
  isTerminal,
  runDurationMs,
  runStatusView,
  shouldPoll
} from "./run-status";
import { CancelRunButton, RetryRunButton, runActions, type RunActionNotice } from "./run-actions";
import { ReviewPanel } from "./review-panel";
import {
  activeReviewQueryOptions,
  getRunGraph,
  getRunStatus,
  redispatchRun,
  runDetailQueryOptions,
  runKeys,
  runStepsQueryOptions,
  type RunDetail,
  type RunSummary
} from "./runs-api";
import { useNowAt } from "./use-now-at";

type Notice = RunActionNotice;

/** The files the run's final result carries. */
function resultFileIds(result: RunDetail["result"]): Set<string> {
  if (result?.kind === "artifact") return new Set(result.files.map((file) => file.file_id));
  if (result?.kind === "file_backed_text") return new Set([result.file.file_id]);
  return new Set();
}

/**
 * Every other file the run's steps made, beside its result: what most
 * people open a finished run for, a click away without going through the
 * steps.
 */
function RunOtherFiles({ flowId, run }: { flowId: string; run: RunDetail }) {
  const t = useTranslations();
  const carried = resultFileIds(run.result);
  const others = (run.result_files ?? []).filter((file) => !carried.has(file.file_id));
  if (others.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <p className="text-ax-text m-0 text-sm font-medium">{t("flow_run_more_other_files")}</p>
      <RunFiles
        flowId={flowId}
        runId={run.id}
        files={others}
        label={t("flow_run_more_other_files")}
      />
    </div>
  );
}

/** The run's final result, by its kind. */
function RunResult({ flowId, run }: { flowId: string; run: RunDetail }) {
  const t = useTranslations();
  const result = run.result;
  if (!result) {
    return (
      <p className="text-ax-text-secondary text-sm">
        {run.status === "completed" ? t("flow_runs_result_none") : t("flow_runs_result_pending")}
      </p>
    );
  }
  switch (result.kind) {
    case "inline_text":
      return <RunText text={result.text} />;
    case "file_backed_text":
      return (
        <div className="flex flex-col gap-2">
          <RunText text={result.preview} />
          <p className="text-ax-text-secondary text-xs">{t("flow_runs_output_overflow")}</p>
          <RunFiles
            flowId={flowId}
            runId={run.id}
            files={[result.file]}
            label={t("flow_runs_result_files")}
          />
        </div>
      );
    case "structured":
      return <JsonValue value={result.value} />;
    case "artifact":
      return (
        <RunFiles
          flowId={flowId}
          runId={run.id}
          files={result.files}
          label={t("flow_runs_result_files")}
        />
      );
    case "outbound_http":
      return <p className="text-ax-text text-sm">{t("flow_runs_result_delivered")}</p>;
  }
}

/** What the run was started with: the form's answers by field label. */
function RunInput({ flow, run }: { flow: FlowPublic; run: RunDetail }) {
  const t = useTranslations();
  const payload = run.input_payload_json ?? {};
  const entries = Object.entries(payload);
  if (entries.length === 0) {
    return <p className="text-ax-text-secondary text-sm">{t("flow_runs_input_none")}</p>;
  }
  // Labels from the flow as it is now; a field renamed since keeps its name.
  const labels = new Map(
    formFieldsOf(flow.metadata_json).map((field) => [field.name, field.label.trim() || field.name])
  );
  return (
    <JsonValue
      value={Object.fromEntries(entries.map(([key, value]) => [labels.get(key) ?? key, value]))}
    />
  );
}

/**
 * What the run used from providers: tokens, with what a token is and what
 * the count covers, and audio for a transcription.
 */
function RunUsage({ run }: { run: RunDetail }) {
  const t = useTranslations();
  const locale = useLocale();
  const tokens = run.token_usage;
  const audio = run.transcription_usage;
  if (!tokens && !audio) return null;
  const total = tokens ? tokenTotal(tokens.num_tokens_input, tokens.num_tokens_output) : null;
  const list = (
    <MetadataList columns="multi">
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
  if (!tokens || total === null) return list;
  return (
    <div className="flex flex-col gap-2">
      {list}
      <p className="text-ax-text-secondary m-0 max-w-prose text-xs">
        {t("flow_runs_usage_tokens_explainer")}
      </p>
    </div>
  );
}

/** Why the run stopped, or why a queued run has not started. */
function RunProblem({
  run,
  flow,
  steps
}: {
  run: RunDetail;
  flow: FlowPublic;
  steps: readonly RunStepView[];
}) {
  const t = useTranslations();
  if (run.status === "failed" && run.error) {
    return (
      <RunFailure
        error={run.error}
        stepName={(order) => steps.find((step) => step.order === order)?.label.trim() || null}
        reviewSteps={flow.steps}
      />
    );
  }
  if (run.status === "cancelled" && run.error) {
    return (
      <Banner
        status="info"
        title={t("flow_runs_cancelled_title")}
        description={runErrorText(run.error, t)}
        collapsible={false}
      />
    );
  }
  if (run.status === "queued" && run.dispatch_last_error) {
    return (
      <Banner
        status="warning"
        title={t("flow_runs_dispatch_problem_title")}
        description={
          run.dispatch_exhausted_at
            ? t("flow_runs_dispatch_exhausted")
            : t("flow_runs_dispatch_retrying")
        }
        collapsible={false}
      />
    );
  }
  return null;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="text-ax-text text-lg font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

/**
 * One run of a flow: its status (kept current while it moves, announced
 * when it changes), why it failed, its result and produced files, each step
 * with its output and evidence, what it was started with, and what it used.
 * Cancel, retry from the failed step and "send again" are offered when the
 * core's own preconditions hold. Polling reads only the content-free status
 * and graph; the audited detail is read again only when they moved.
 */
export function FlowRunPage({ flowId, runId }: { flowId: string; runId: string }) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const { routeId } = useSpace();
  const { can, user } = useAppContext();
  const spaceName = useSpaceDisplayName();
  const sections = useSpaceSections();
  const { data: flow } = useSuspenseQuery(flowQueryOptions(browserApi, flowId));
  const [clock] = useState(() => createPollClock());
  const [notice, setNotice] = useState<Notice | null>(null);
  // A cancelled run's button goes: focus moves to the page's heading.
  const headingRef = useRef<HTMLHeadingElement>(null);
  const rescue = useFocusRescue();
  const lastStatus = useRef<string | null>(null);

  // A poll that answers the same keeps the same data, so the page does not
  // render again: the data carries no clock (`useNowAt` keeps the deadlines),
  // and reading `isFetching` or `dataUpdatedAt` here on the success path
  // would bring back one render per poll.
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

  const signature = progress.data
    ? progressSignature(progress.data.status, progress.data.graph)
    : null;
  const detail = useQuery({
    ...runDetailQueryOptions(browserApi, flowId, runId, signature ?? ""),
    enabled: signature !== null,
    placeholderData: keepPreviousData
  });
  const settled = progress.data ? isTerminal(progress.data.status.status) : false;
  const steps = useQuery({
    ...runStepsQueryOptions(flowId, runId, signature ?? "", settled),
    enabled: signature !== null,
    placeholderData: keepPreviousData
  });
  const awaitingReview = progress.data ? isAwaitingReview(progress.data.status.status) : false;
  const review = useQuery({
    ...activeReviewQueryOptions(flowId, runId, signature ?? ""),
    enabled: awaitingReview
  });

  const summary: RunSummary | undefined = progress.data?.status;
  const status = summary?.status ?? null;
  // "Send again" and a review's decision turn at their deadline, not at the next poll.
  const now = useNowAt([
    summary?.dispatch_next_attempt_at,
    awaitingReview ? review.data?.expires_at : null
  ]);
  const stepViews = progress.data ? runStepViews(progress.data.graph, steps.data) : [];
  // A review of a transcript shows it, correctable, in the review itself.
  const reviewTranscript =
    awaitingReview && review.data
      ? reviewTranscriptTarget(
          review.data,
          reviewDraftOf(review.data).kind === "speakers",
          steps.data
        )
      : null;

  // Announces a status the run moved to while the page is open.
  useEffect(() => {
    if (status && lastStatus.current && lastStatus.current !== status) {
      announce(t("flow_runs_status_now", { status: t(runStatusView(status).labelKey) }));
    }
    lastStatus.current = status;
  }, [announce, status, t]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: runKeys.run(flowId, runId) });
  const [refreshing, setRefreshing] = useState(false);
  // Reads everything on the page again, the audited content included: the person asked.
  async function refreshNow() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await refresh();
      announce(t("flow_run_more_refreshed"));
    } finally {
      setRefreshing(false);
    }
  }

  const redispatch = useMutation({
    mutationFn: (run: RunSummary) => redispatchRun(flowId, run),
    onSuccess: (answer) => {
      void refresh();
      setNotice(
        answer.redispatched_count > 0
          ? { status: "success", title: t("flow_runs_redispatch_done") }
          : { status: "info", title: t("flow_runs_redispatch_noop") }
      );
    },
    onError: (error) =>
      setNotice({
        status: "error",
        title: t("flow_runs_redispatch_failed"),
        description: refusalText(error, t)
      })
  });

  const run = detail.data;
  const startedAt = summary ? (summary.started_at ?? summary.created_at) : null;
  const time = useClientTimeText(startedAt, "date_time");
  const title =
    run?.run_label?.trim() ||
    (time ? t("flow_runs_run_title", { time }) : t("flow_runs_run_title_plain"));

  // Retrying needs the principal that started the run; said up front, not on refusal.
  const offers = summary
    ? runActions(summary, {
        canRun: can("flows_run"),
        userId: user.id,
        publishedVersion: flow.published_version
      })
    : null;
  const offersRedispatch = summary !== undefined && canRedispatch(summary, now);

  const actions = summary ? (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        label={t("flow_run_more_refresh")}
        icon={<RefreshCw aria-hidden="true" />}
        onClick={() => void refreshNow()}
        isLoading={refreshing}
        isInterruptible
      />
      {offersRedispatch ? (
        <Button
          label={t("flow_runs_redispatch")}
          onClick={() => {
            if (!redispatch.isPending) redispatch.mutate(summary);
          }}
          isLoading={redispatch.isPending}
          isInterruptible
        />
      ) : null}
      {offers?.retry ? (
        <RetryRunButton
          spaceRouteId={routeId}
          flowId={flowId}
          runId={runId}
          report={setNotice}
          variant="primary"
        />
      ) : null}
      {offers?.cancel ? (
        <CancelRunButton
          flowId={flowId}
          runId={runId}
          report={setNotice}
          onCancelled={() => rescue(() => headingRef.current)}
        />
      ) : null}
    </div>
  ) : undefined;

  const view = status ? runStatusView(status) : null;
  const duration = summary ? runDurationMs(summary) : null;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="border-ax-border flex flex-col gap-3 border-b px-6 pt-4 pb-3">
        <PageHeader
          title={title}
          headingRef={headingRef}
          breadcrumbs={[
            { label: spaceName, href: spaceLandingHref(sections, routeId) },
            { label: t("flows"), href: `/spaces/${routeId}/flows` },
            { label: flow.name, href: `/spaces/${routeId}/flows/${flowId}?tab=runs` },
            { label: title, current: true }
          ]}
          actions={actions}
        />
        {summary && view ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <StatusLabel status={view.tone} label={t(view.labelKey)} isPulsing={view.isPulsing} />
            {startedAt ? (
              <span className="text-ax-text-secondary">
                {t("flow_runs_started_at")} <ClientTime value={startedAt} format="date_time" />
              </span>
            ) : null}
            {duration !== null ? (
              <span className="text-ax-text-secondary">
                {t("flow_runs_took", { time: formatSeconds(duration / 1000, t) })}
              </span>
            ) : null}
            <span className="text-ax-text-secondary">
              {t("flow_runs_version", { version: summary.flow_version })}
            </span>
            <span className="text-ax-text-secondary">
              {t("flow_runs_started_by_named", { name: starterName(summary, t) })}
            </span>
          </div>
        ) : null}
        {offers?.retryHeldBack === "version_changed" ? (
          <p className="text-ax-text-secondary text-sm">{t("flow_runs_retry_version_changed")}</p>
        ) : null}
        {summary && offers?.retryHeldBack === "starter_only" ? (
          <p className="text-ax-text-secondary text-sm">
            {t("flow_runs_retry_starter_only", { name: starterName(summary, t) })}
          </p>
        ) : null}
        {notice ? (
          <Banner
            status={notice.status}
            title={notice.title}
            description={notice.description}
            endContent={
              notice.link ? (
                <Button label={notice.link.label} href={notice.link.href} size="sm" />
              ) : undefined
            }
            collapsible={false}
            isDismissable
            dismissLabel={t("flows_notice_dismiss")}
            onDismiss={() => setNotice(null)}
          />
        ) : null}
      </div>

      <div className="flex w-full max-w-5xl flex-col gap-8 px-6 py-5">
        {progress.isPending ? (
          <LoadingState rows={4} label={t("flow_runs_run_loading")} />
        ) : progress.isError ? (
          <ListError
            error={progress.error}
            title={t("flow_runs_run_failed_to_load")}
            onRetry={() => void progress.refetch()}
            isRetrying={progress.isFetching}
          />
        ) : (
          <>
            {run ? <RunProblem run={run} flow={flow} steps={stepViews} /> : null}
            {awaitingReview && review.isError ? (
              <ListError
                error={review.error}
                title={t("flow_runs_review_failed_to_load")}
                onRetry={() => void review.refetch()}
                isRetrying={review.isFetching}
              />
            ) : awaitingReview && review.data ? (
              <ReviewPanel
                key={`${review.data.id}:${review.data.revision}`}
                checkpoint={review.data}
                transcript={reviewTranscript}
                mayReview={can("flows_manage")}
                now={now}
                onStale={(message) =>
                  setNotice({
                    status: "warning",
                    title: t("flow_runs_review_stale_title"),
                    description: message
                  })
                }
              />
            ) : null}
            <Section title={t("flow_runs_result_heading")}>
              {detail.isError ? (
                <ListError
                  error={detail.error}
                  title={t("flow_runs_detail_failed")}
                  onRetry={() => void detail.refetch()}
                  isRetrying={detail.isFetching}
                />
              ) : run ? (
                <>
                  <RunResult flowId={flowId} run={run} />
                  <RunOtherFiles flowId={flowId} run={run} />
                </>
              ) : (
                <LoadingState rows={2} />
              )}
            </Section>
            <Section title={t("flow_runs_steps_heading")}>
              {steps.isError ? (
                <ListError
                  error={steps.error}
                  title={t("flow_runs_steps_failed")}
                  onRetry={() => void steps.refetch()}
                  isRetrying={steps.isFetching}
                />
              ) : (
                <>
                  <RunLiveProgress summary={progress.data.status} steps={stepViews} />
                  <RunSteps
                    flowId={flowId}
                    runId={runId}
                    steps={stepViews}
                    runStatus={status}
                    canReadEvidence={run?.evidence_access.can_read_evidence ?? false}
                  />
                </>
              )}
            </Section>
            {transcriptTargets(steps.data).length > 0 && !reviewTranscript ? (
              <Section title={t("flow_runs_transcript_heading")}>
                <RunTranscripts
                  flowId={flowId}
                  runId={runId}
                  targets={transcriptTargets(steps.data)}
                  labelFor={(target) =>
                    stepTitle(
                      stepViews.find((step) => step.order === target.stepOrder) ?? {
                        order: target.stepOrder,
                        label: ""
                      },
                      t
                    )
                  }
                  mayEdit={can("flows_manage")}
                  runCompleted={status === "completed"}
                  runRevision={summary?.revision ?? null}
                />
              </Section>
            ) : null}
            {run?.evidence_access.can_read_evidence ? (
              <Section title={t("flow_runs_knowledge_heading")}>
                <RunKnowledge
                  flowId={flowId}
                  runId={runId}
                  steps={stepViews}
                  runSettled={settled}
                />
              </Section>
            ) : null}
            {run ? (
              <>
                <Section title={t("flow_runs_input_heading")}>
                  <RunInput flow={flow} run={run} />
                </Section>
                {run.token_usage || run.transcription_usage ? (
                  <Section title={t("flow_runs_usage_heading")}>
                    <RunUsage run={run} />
                  </Section>
                ) : null}
                {run.webhook_deliveries.length > 0 ? (
                  <Section title={t("flow_run_extras_webhook_heading")}>
                    <RunWebhookDeliveries
                      deliveries={run.webhook_deliveries}
                      stepName={(order) =>
                        stepTitle(
                          stepViews.find((step) => step.order === order) ?? { order, label: "" },
                          t
                        )
                      }
                    />
                  </Section>
                ) : null}
              </>
            ) : null}
            {summary ? (
              <RunTrace
                flow={flow}
                summary={summary}
                steps={stepViews}
                access={run?.evidence_access}
              />
            ) : null}
            {summary ? (
              <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
                <CopyableValue
                  label={t("flow_run_more_run_id")}
                  value={summary.id}
                  hint={t("flow_run_more_run_id_hint")}
                />
                <CopyableValue
                  label={t("flow_run_more_trace_id")}
                  value={summary.trace_id}
                  hint={t("flow_run_more_trace_id_hint")}
                />
              </dl>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
