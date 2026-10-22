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
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { QuietBanner } from "@/components/astryx/banner";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { ListError } from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { useSpaceDisplayName, useSpaceSections } from "@/features/spaces/frame/space-header";
import { spaceLandingHref } from "@/features/spaces/frame/space-sections";
import { useSpace } from "@/features/spaces/use-space";
import { formFieldsOf } from "../flow-form-fields";
import { flowQueryOptions, type FlowPublic } from "../flows-api";
import { formatCount, formatSeconds } from "./run-format";
import { RunFiles } from "./run-files";
import { JsonValue } from "./run-json";
import { refusalText, runErrorText } from "./run-messages";
import { progressSignature, runStepViews, tokenTotal } from "./run-progress";
import { RunKnowledge } from "./run-knowledge";
import { startedByUser, starterName } from "./run-starter";
import { RunSteps, stepTitle } from "./run-steps";
import { RunTranscripts } from "./run-transcript";
import { reviewTranscriptTarget, transcriptTargets } from "./transcript";
import { reviewDraftOf } from "./review-draft";
import {
  canRedispatch,
  createPollClock,
  isAwaitingReview,
  isCancellable,
  runDurationMs,
  runStatusView,
  shouldPoll
} from "./run-status";
import { ReviewPanel } from "./review-panel";
import {
  activeReviewQueryOptions,
  cancelRun,
  getRunGraph,
  getRunStatus,
  newIdempotencyKey,
  redispatchRun,
  retryRun,
  runDetailQueryOptions,
  runKeys,
  runStepsQueryOptions,
  type RunDetail,
  type RunSummary
} from "./runs-api";
import { runHref } from "./runs-list";

type Notice = {
  status: "error" | "warning" | "info" | "success";
  title: string;
  description?: string;
};

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
      return <p className="text-ax-text text-sm break-words whitespace-pre-wrap">{result.text}</p>;
    case "file_backed_text":
      return (
        <div className="flex flex-col gap-2">
          <p className="text-ax-text text-sm break-words whitespace-pre-wrap">{result.preview}</p>
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

/** What the run used from providers: tokens, and audio for a transcription. */
function RunUsage({ run }: { run: RunDetail }) {
  const t = useTranslations();
  const locale = useLocale();
  const tokens = run.token_usage;
  const audio = run.transcription_usage;
  if (!tokens && !audio) return null;
  const total = tokens ? tokenTotal(tokens.num_tokens_input, tokens.num_tokens_output) : null;
  return (
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
}

/** Why the run stopped, or why a queued run has not started. */
function RunProblem({ run }: { run: RunDetail }) {
  const t = useTranslations();
  if (run.status === "failed" && run.error) {
    return (
      <QuietBanner
        status="error"
        title={t("flow_runs_failed_title")}
        description={runErrorText(run.error, t)}
        collapsible={false}
      />
    );
  }
  if (run.status === "cancelled" && run.error) {
    return (
      <QuietBanner
        status="info"
        title={t("flow_runs_cancelled_title")}
        description={runErrorText(run.error, t)}
        collapsible={false}
      />
    );
  }
  if (run.status === "queued" && run.dispatch_last_error) {
    return (
      <QuietBanner
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
  const router = useRouter();
  const { routeId } = useSpace();
  const { can, user } = useAppContext();
  const spaceName = useSpaceDisplayName();
  const sections = useSpaceSections();
  const { data: flow } = useSuspenseQuery(flowQueryOptions(browserApi, flowId));
  const [clock] = useState(() => createPollClock());
  const [notice, setNotice] = useState<Notice | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const retryKey = useRef<string | null>(null);
  const lastStatus = useRef<string | null>(null);

  const progress = useQuery({
    queryKey: runKeys.progress(flowId, runId),
    queryFn: async ({ signal }) => {
      const [status, graph] = await Promise.all([
        getRunStatus(flowId, runId, signal),
        getRunGraph(flowId, runId, signal)
      ]);
      return { status, graph, checkedAt: Date.now() };
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
  const steps = useQuery({
    ...runStepsQueryOptions(flowId, runId, signature ?? ""),
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

  const cancel = useMutation({
    mutationFn: () => cancelRun(flowId, runId),
    onSuccess: (run) => {
      setConfirmCancel(false);
      void refresh();
      void queryClient.invalidateQueries({ queryKey: runKeys.list(flowId) });
      // Cancelling a run that already ended returns it unchanged.
      if (run.status === "cancelled") announce(t("flow_runs_cancel_done"));
      else {
        setNotice({
          status: "info",
          title: t("flow_runs_cancel_already_ended", {
            status: t(runStatusView(run.status).labelKey)
          })
        });
      }
    },
    onError: (error) => {
      setConfirmCancel(false);
      setNotice({
        status: "error",
        title: t("flow_runs_cancel_failed"),
        description: refusalText(error, t)
      });
    }
  });

  const retry = useMutation({
    mutationFn: () => {
      // One key per retry of this run: a lost response replays the same child.
      retryKey.current ??= newIdempotencyKey();
      return retryRun(flowId, runId, retryKey.current);
    },
    onSuccess: (child) => {
      void queryClient.invalidateQueries({ queryKey: runKeys.list(flowId) });
      announce(t("flow_runs_retry_started", { order: child.first_executed_step_order }));
      router.push(runHref(routeId, flowId, child.run.id));
    },
    onError: (error) => {
      if (error instanceof EneoApiError && error.reason === "flow_run_idempotency_conflict") {
        retryKey.current = null;
      }
      setNotice({
        status: "error",
        title: t("flow_runs_retry_failed"),
        description: refusalText(error, t)
      });
    }
  });

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

  const canRun = can("flows_run");
  const isCurrentVersion = summary ? summary.flow_version === flow.published_version : false;
  const offersRetry = canRun && status === "failed";
  // Retrying needs the principal that started the run; said up front, not on refusal.
  const retryNeedsStarter =
    offersRetry &&
    isCurrentVersion &&
    summary !== undefined &&
    startedByUser(summary, user.id) === false;
  const offersCancel = status !== null && isCancellable(status);
  const offersRedispatch =
    summary !== undefined &&
    progress.data !== undefined &&
    canRedispatch(summary, progress.data.checkedAt);

  const actions = summary ? (
    <div className="flex flex-wrap items-center gap-2">
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
      {offersRetry && isCurrentVersion && !retryNeedsStarter ? (
        <Button
          label={t("flow_runs_retry")}
          variant="primary"
          onClick={() => {
            if (!retry.isPending) retry.mutate();
          }}
          isLoading={retry.isPending}
          isInterruptible
        />
      ) : null}
      {offersCancel ? (
        <Button
          label={t("flow_runs_cancel")}
          variant="destructive"
          onClick={() => setConfirmCancel(true)}
          isLoading={cancel.isPending}
          isInterruptible
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
        {offersRetry && !isCurrentVersion ? (
          <p className="text-ax-text-secondary text-sm">{t("flow_runs_retry_version_changed")}</p>
        ) : null}
        {retryNeedsStarter ? (
          <p className="text-ax-text-secondary text-sm">
            {t("flow_runs_retry_starter_only", { name: starterName(summary, t) })}
          </p>
        ) : null}
        {notice ? (
          <QuietBanner
            status={notice.status}
            title={notice.title}
            description={notice.description}
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
            {run ? <RunProblem run={run} /> : null}
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
                now={progress.data.checkedAt}
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
                <RunResult flowId={flowId} run={run} />
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
                <RunSteps
                  flowId={flowId}
                  runId={runId}
                  steps={runStepViews(progress.data.graph, steps.data)}
                />
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
                      runStepViews(progress.data.graph, steps.data).find(
                        (step) => step.order === target.stepOrder
                      ) ?? { order: target.stepOrder, label: "" },
                      t
                    )
                  }
                  mayEdit={can("flows_manage")}
                  runCompleted={status === "completed"}
                  runRevision={summary?.revision ?? null}
                />
              </Section>
            ) : null}
            <Section title={t("flow_runs_knowledge_heading")}>
              <RunKnowledge
                flowId={flowId}
                runId={runId}
                steps={runStepViews(progress.data.graph, steps.data)}
              />
            </Section>
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
              </>
            ) : null}
            <p className="text-ax-text-secondary text-xs">
              {t("flow_runs_trace_id", { id: summary?.trace_id ?? "" })}
            </p>
          </>
        )}
      </div>

      <ConfirmDialogControlled
        open={confirmCancel}
        onOpenChange={(open) => {
          if (!cancel.isPending) setConfirmCancel(open);
        }}
        title={t("flow_runs_cancel_title")}
        description={t("flow_runs_cancel_description")}
        confirmLabel={t("flow_runs_cancel")}
        pending={cancel.isPending}
        onConfirm={() => cancel.mutate()}
      />
    </div>
  );
}
