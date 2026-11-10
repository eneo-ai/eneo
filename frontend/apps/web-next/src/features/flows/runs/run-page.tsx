import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Tooltip } from "@astryxdesign/core/Tooltip";
import { Collapsible } from "@/components/astryx/collapsible";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Info, RefreshCw } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal, flushSync } from "react-dom";
import { Banner } from "@astryxdesign/core/Banner";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { LoadingState } from "@/components/composites/loading-state";
import { PageHeader } from "@/components/composites/page-header";
import { blockingError, ListError, RefreshError } from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { hasAnswered, pollEvery } from "@/lib/api/query";
import { useFocusRescue } from "@/lib/focus-rescue";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";
import { useSpaceSections } from "@/features/spaces/frame/use-space-sections";
import { useSpaceDisplayName } from "@/features/spaces/space-display-name";
import { spaceLandingHref } from "@/features/spaces/frame/space-sections";
import { useSpace } from "@/features/spaces/use-space";
import { formFieldsOf } from "../flow-form-fields";
import { FlowRunStarter } from "../flow-run-starter";
import { flowQueryOptions, type FlowPublic } from "../flows-api";
import { CopyButton } from "./run-copy";
import { formatSeconds } from "./run-format";
import { RunFailure } from "./run-failure";
import { RunWebhookDeliveries } from "./run-webhooks";
import { RunFiles } from "./run-files";
import { JsonValue } from "./run-json";
import { refusalText, runErrorText, stepWarningText } from "./run-messages";
import { outputText, progressSignature, runStepViews, type RunStepView } from "./run-progress";
import { RunLiveProgress } from "./run-live-progress";
import { RunKnowledge, searchedKnowledge } from "./run-knowledge";
import { starterName } from "./run-starter";
import {
  RunSteps,
  showRunStep,
  StepText,
  StepTextInsteadOfTranscript,
  stepTitle
} from "./run-steps";
import { RunText } from "./run-text";
import { RunUsage, RunUsageBrief } from "./run-usage";
import { RunTrace } from "./run-trace";
import { RunTranscript, useTranscriptHosts } from "./run-transcript";
import { mappedSpeakerNames } from "./run-step-facts";
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
  type RunGraph,
  type RunSummary
} from "./runs-api";
import { useNowAt } from "./use-now-at";
import { useShownRead } from "./use-shown-read";

type Notice = RunActionNotice;

/** Step warnings that say the run lost part of what it was given. */
const INPUT_LOSS_CODES = new Set([
  "runtime_input_source_text_unavailable",
  "empty_prior_step_input"
]);

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

/**
 * What a copy of the run's result gives: its text or value. A result in a
 * file, a shortened text with it, is downloaded: a copy would be cut short.
 */
function copyableResult(result: RunDetail["result"] | undefined): unknown {
  if (result?.kind === "inline_text") return result.text;
  return result?.kind === "structured" ? result.value : null;
}

/**
 * The run's final result, by its kind. A run that stopped with none points
 * to the last step that finished, whose result is in the steps.
 */
function RunResult({
  flowId,
  run,
  steps
}: {
  flowId: string;
  run: RunDetail;
  steps: readonly RunStepView[];
}) {
  const t = useTranslations();
  const result = run.result;
  if (!result) {
    const stopped = run.status === "failed" || run.status === "cancelled";
    const finished = steps.findLast((step) => step.status === "completed");
    return (
      <p className="text-ax-text-secondary text-sm">
        {run.status === "completed"
          ? t("flow_runs_result_none")
          : stopped && finished
            ? t("flow_runs_result_none_after_step", { order: finished.order })
            : stopped
              ? t("flow_runs_result_none_stopped")
              : t("flow_runs_result_pending")}
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
  // Free text is sent as `{ text }`: no field to name, only the text.
  const { text } = payload;
  if (entries.length === 1 && !labels.has("text") && typeof text === "string" && text.trim()) {
    return <StepText text={text} label={t("flow_runs_form_answers_heading")} plain />;
  }
  return (
    <JsonValue
      value={Object.fromEntries(entries.map(([key, value]) => [labels.get(key) ?? key, value]))}
    />
  );
}

/** Why the run stopped, or why a queued run has not started. */
function RunProblem({
  run,
  flow,
  steps,
  onShowStep,
  rerunOffered
}: {
  run: RunDetail;
  flow: FlowPublic;
  steps: readonly RunStepView[];
  onShowStep: (order: number) => void;
  rerunOffered: boolean;
}) {
  const t = useTranslations();
  if (run.status === "failed" && run.error) {
    return (
      <RunFailure
        error={run.error}
        stepName={(order) => steps.find((step) => step.order === order)?.label.trim() || null}
        reviewSteps={flow.steps}
        onShowStep={onShowStep}
        rerunOffered={rerunOffered}
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

/**
 * A support id beside the run's status, short: its first characters, a
 * button that copies all of it, and what it is for, with the whole id, behind
 * an info button (hover, focus or tap).
 */
function RunId({ label, value, hint }: { label: string; value: string; hint: string }) {
  const t = useTranslations();
  return (
    <span className="text-ax-text-secondary inline-flex min-w-0 items-center gap-1">
      {label}
      <code className="text-ax-text font-mono text-xs">
        {value.length > 8 ? `${value.slice(0, 8)}…` : value}
      </code>
      <CopyButton label={t("chat_debug_copy_value", { label })} value={value} />
      <Tooltip
        content={
          <span className="flex flex-col gap-1">
            <span>{hint}</span>
            <code className="font-mono text-xs [overflow-wrap:anywhere]">{value}</code>
          </span>
        }
        touchTrigger="tap"
      >
        <IconButton
          label={t("chat_debug_value_about", { label })}
          icon={<Info className="size-3.5" />}
          variant="ghost"
          size="sm"
        />
      </Tooltip>
    </span>
  );
}

function Section({
  title,
  action,
  children
}: {
  title: string;
  /** Beside the heading, at the row's end. */
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 id={headingId} className="text-ax-text text-lg font-semibold">
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/**
 * A section folded away: the result is what the page is for, and what was
 * asked, what it cost and the evidence are one tap below it, at every width.
 */
function FoldSection({
  title,
  defaultIsOpen = false,
  isOpen,
  onOpenChange,
  children
}: {
  title: string;
  defaultIsOpen?: boolean;
  isOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} className="border-ax-border border-t pt-1">
      <Collapsible
        // A thumb's height, not the text's. Block-level: Astryx trims the trigger's label to its
        // cap height, which an inline box's own min-height cannot get past (it measured 17 px).
        trigger={<span className="flex min-h-6 items-center pointer-coarse:min-h-11">{title}</span>}
        defaultIsOpen={defaultIsOpen}
        isOpen={isOpen}
        onOpenChange={onOpenChange}
        className="w-full"
      >
        <div className="pt-2 pb-1">
          {/* The section's heading, so what is inside does not read as part of the section above. */}
          <h2 className="sr-only">{title}</h2>
          {children}
        </div>
      </Collapsible>
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
  // A phone has the space's header above the page already: no breadcrumbs here, no gutter of
  // its own (the space's frame gives one), and the steps folded.
  const phone = usePhoneScreen();
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
    refetchInterval: pollEvery<{ status: RunSummary; graph: RunGraph }>((data) =>
      data
        ? clock(progressSignature(data.status, data.graph), shouldPoll(data.status.status))
        : false
    ),
    refetchIntervalInBackground: false
  });

  const signature = progress.data
    ? progressSignature(progress.data.status, progress.data.graph)
    : null;
  // Until the run shows, its detail and steps keep the signature they began with: a run that moves
  // on faster than they answer would otherwise start them over each time and never show. The review
  // follows the live signature: a run waiting for review does not move, and a review keyed by an
  // older signature would be read again, and its panel arrive late, once the page shows.
  const [shown, setShown] = useState(false);
  const [firstSignature, setFirstSignature] = useState<string | null>(null);
  if (firstSignature === null && signature !== null) setFirstSignature(signature);
  const readSignature = shown ? signature : firstSignature;
  const detail = useShownRead(
    useQuery({
      ...runDetailQueryOptions(browserApi, flowId, runId, readSignature ?? ""),
      enabled: readSignature !== null
    })
  );
  const settled = progress.data ? isTerminal(progress.data.status.status) : false;
  const steps = useShownRead(
    useQuery({
      ...runStepsQueryOptions(flowId, runId, readSignature ?? "", settled),
      enabled: readSignature !== null
    })
  );
  const awaitingReview = progress.data ? isAwaitingReview(progress.data.status.status) : false;
  const review = useQuery({
    ...activeReviewQueryOptions(flowId, runId, signature ?? ""),
    enabled: awaitingReview
  });
  // The run shows once its first reads are in, and stays shown: the status and graph, then the
  // detail and steps they unlock (and an open review). Shown as each arrived, the header's status
  // line and title and each section pushed what was already on the screen (layout shift 0.20 on a
  // phone). A read that failed shows the page with its error, also while it is retried
  // (`hasAnswered`, which reads only `isPending` and `failureCount`: other fields, `fetchStatus`
  // and the update times `blockingError` reads among them, would render the page on every poll).
  const firstReads = [
    progress,
    ...(signature !== null ? [detail, steps] : []),
    ...(awaitingReview ? [review] : [])
  ];
  if (!shown && firstReads.every(hasAnswered)) setShown(true);

  const summary: RunSummary | undefined = progress.data?.status;
  const status = summary?.status ?? null;
  const [stepsOpen, setStepsOpen] = useState<boolean | null>(null);
  function revealStep(order: number) {
    flushSync(() => setStepsOpen(true));
    showRunStep(order);
  }
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
  // Each transcript shows once: in its step, or in the review while one is about a transcript.
  const transcripts = reviewTranscript ? [] : transcriptTargets(steps.data);
  // Each step's transcript speakers as the run's speaker-mapping step named them.
  const mappedNames = useMemo(() => {
    const all = steps.data ?? [];
    return new Map(all.map((step) => [step.step_id, mappedSpeakerNames(all, step.step_id)]));
  }, [steps.data]);
  const transcriptHost = useTranscriptHosts();
  // The first status the page shows sets the default; finishing must not fold what someone is
  // reading. A run with a transcript opens its steps on a phone too: the transcript is in them.
  if (stepsOpen === null && shown && status !== null) {
    setStepsOpen(status !== "completed" || transcripts.length > 0);
  }

  // Announces a status the run moved to while the page is open.
  useEffect(() => {
    if (status && lastStatus.current && lastStatus.current !== status) {
      announce(t("flow_runs_status_now", { status: t(runStatusView(status).labelKey) }));
    }
    lastStatus.current = status;
  }, [announce, status, t]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: runKeys.run(flowId, runId) });
  const [refreshing, setRefreshing] = useState(false);
  // Reads everything on the page again, the audited content and the transcripts
  // included: the person asked.
  async function refreshNow() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await Promise.all([
        refresh(),
        queryClient.invalidateQueries({ queryKey: runKeys.transcripts(flowId, runId) })
      ]);
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
  const resultCopy = copyableResult(run?.result);
  const startedAt = summary ? (summary.started_at ?? summary.created_at) : null;
  const time = useClientTimeText(startedAt, "date_time");
  const title =
    run?.run_label?.trim() ||
    (time ? t("flow_runs_run_title", { time }) : t("flow_runs_run_title_plain"));

  // Retrying needs the principal that started the run; said up front, not on refusal.
  const offers = summary
    ? runActions(
        summary,
        {
          canRun: can("flows_run") && flow.permissions.can_run,
          userId: user.id,
          publishedVersion: flow.published_version
        },
        { steps: stepViews }
      )
    : null;
  const [starting, setStarting] = useState(false);
  // A finished run that lost an input: done, but its result may miss what the person sent.
  const inputLoss =
    status === "completed"
      ? [
          ...new Set(
            stepViews.flatMap((step) =>
              (step.result?.diagnostics ?? [])
                .filter((item) => INPUT_LOSS_CODES.has(item.code))
                .map((item) => stepWarningText(item.code, t) ?? "")
            )
          )
        ].filter(Boolean)
      : [];
  const offersRedispatch = summary !== undefined && canRedispatch(summary, now);

  // A finished run no longer changes: reading it again is offered only after a read failed.
  const offersRefresh = !settled || [progress, detail, steps].some((read) => read.isError);

  const actions = summary ? (
    <div className="flex flex-wrap items-center gap-2">
      {offersRefresh ? (
        <Button
          label={t("flow_run_more_refresh")}
          icon={<RefreshCw aria-hidden="true" />}
          onClick={() => void refreshNow()}
          isLoading={refreshing}
          isInterruptible
        />
      ) : null}
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
          variant={offers.primary === "retry" ? "primary" : "secondary"}
        />
      ) : null}
      {offers?.newRun ? (
        <Button
          label={t("flow_runs_new_run")}
          variant={offers.primary === "new_run" ? "primary" : "secondary"}
          onClick={() => setStarting(true)}
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

  const pendingDeliveries = (run?.webhook_deliveries ?? []).filter(
    (delivery) => delivery.delivery_status === "pending"
  );
  const deliveryUnderWay =
    pendingDeliveries.length === 0
      ? null
      : pendingDeliveries.some((delivery) => delivery.delivery_attempts > 0)
        ? "retrying"
        : "sending";
  const stepsBody = summary ? (
    <>
      {blockingError(steps) ? (
        <ListError
          error={steps.error}
          title={t("flow_runs_steps_failed")}
          onRetry={() => void steps.refetch()}
          isRetrying={steps.isFetching}
        />
      ) : (
        <>
          <RunLiveProgress summary={summary} steps={stepViews} delivery={deliveryUnderWay} />
          <RunSteps
            flowId={flowId}
            runId={runId}
            steps={stepViews}
            runStatus={status}
            failureShownFor={status === "failed" ? (detail.data?.error?.step_order ?? null) : null}
            transcripts={
              new Map(transcripts.map((target) => [target.stepId, transcriptHost(target.stepId)]))
            }
          />
        </>
      )}
    </>
  ) : null;
  // The steps fold on a phone only: from a tablet up they are the page's body, open.
  const stepsSection = !stepsBody ? null : phone ? (
    <FoldSection
      title={t("flow_runs_steps_heading")}
      isOpen={stepsOpen ?? false}
      onOpenChange={setStepsOpen}
    >
      {stepsBody}
    </FoldSection>
  ) : (
    <Section title={t("flow_runs_steps_heading")}>{stepsBody}</Section>
  );
  // Rendered here, where nothing moves, and shown in the steps (`useTranscriptHosts`).
  const transcriptViews = transcripts.map((target) => {
    const result = steps.data?.find((step) => step.step_id === target.stepId);
    const text = result ? outputText(result.output_payload_json) : null;
    return createPortal(
      <RunTranscript
        flowId={flowId}
        runId={runId}
        target={target}
        mayEdit={can("flows_manage")}
        runCompleted={status === "completed"}
        runRevision={summary?.revision ?? null}
        proposedNames={mappedNames.get(target.stepId)}
        // A transcribing step whose transcript has no lines still shows what it wrote.
        fallback={
          text && stepViews.find((step) => step.order === target.stepOrder)?.transcribeOnly ? (
            <StepTextInsteadOfTranscript payload={result?.output_payload_json} />
          ) : undefined
        }
      />,
      transcriptHost(target.stepId),
      target.stepId
    );
  });

  // On a phone a run waiting for review leads with the decision: refreshing or cancelling the
  // whole run comes after the review panel, not between the title and it.
  const actionsAfterReview = phone && awaitingReview;
  const view = status ? runStatusView(status) : null;
  const duration = summary ? runDurationMs(summary) : null;

  if (!shown) {
    return (
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex w-full max-w-5xl flex-col py-4 md:py-5">
          <LoadingState rows={4} label={t("flow_runs_run_loading")} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="border-ax-border flex flex-col gap-3 border-b pt-4 pb-3">
        <PageHeader
          title={title}
          headingRef={headingRef}
          breadcrumbs={
            // The space's phone header stands in for the breadcrumbs, held either way.
            phone
              ? undefined
              : [
                  { label: spaceName, href: spaceLandingHref(sections, routeId) },
                  { label: t("flows"), href: `/spaces/${routeId}/flows` },
                  { label: flow.name, href: `/spaces/${routeId}/flows/${flowId}?tab=runs` },
                  // The h1 below names the run in full; the trail only says where it is, so it
                  // stays on one line beside the icon rail.
                  { label: t("flow_runs_run_title_plain"), current: true }
                ]
          }
          actions={actionsAfterReview ? undefined : actions}
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
            {run ? <RunUsageBrief run={run} /> : null}
          </div>
        ) : null}
        {offers?.heldBack === "unpublished" ? (
          <p className="text-ax-text-secondary text-sm">{t("flow_runs_not_published")}</p>
        ) : null}
        {offers?.heldBack === "version_changed" ? (
          <p className="text-ax-text-secondary text-sm">{t("flow_runs_retry_version_changed")}</p>
        ) : null}
        {summary && offers?.heldBack === "starter_only" ? (
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

      <div className="flex w-full max-w-5xl flex-col gap-6 py-4 md:gap-8 md:py-5">
        {blockingError({
          data: progress.data,
          isError: progress.isError,
          isPending: progress.isPending,
          errorUpdatedAt: progress.errorUpdatedAt,
          // It moves on every poll, so reading it would render the page on each one, and it
          // decides nothing here: a read without data has none (0).
          dataUpdatedAt: 0
        }) ? (
          <ListError
            error={progress.error}
            title={t("flow_runs_run_failed_to_load")}
            onRetry={() => void progress.refetch()}
            // Pending again is the retry in flight; `isFetching` moves on every poll as well.
            isRetrying={progress.isPending}
          />
        ) : progress.isPending ? (
          <LoadingState rows={4} label={t("flow_runs_run_loading")} />
        ) : (
          <>
            {/* A failed poll or read again keeps the run, and a review's draft, on the page. */}
            <RefreshError
              queries={[progress, detail, steps, ...(awaitingReview ? [review] : [])]}
            />
            {run ? (
              <RunProblem
                run={run}
                flow={flow}
                steps={stepViews}
                onShowStep={revealStep}
                rerunOffered={Boolean(offers?.retry || offers?.newRun)}
              />
            ) : null}
            {inputLoss.length > 0 ? (
              <Banner
                status="warning"
                title={t("flow_runs_input_loss_title")}
                description={inputLoss.join(" ")}
                collapsible={false}
              />
            ) : null}
            {awaitingReview && blockingError(review) ? (
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
            {actionsAfterReview ? actions : null}
            <Section
              title={t("flow_runs_result_heading")}
              action={
                resultCopy ? (
                  <CopyButton label={t("flow_run_more_copy_output")} value={resultCopy} />
                ) : null
              }
            >
              {blockingError(detail) ? (
                <ListError
                  error={detail.error}
                  title={t("flow_runs_detail_failed")}
                  onRetry={() => void detail.refetch()}
                  isRetrying={detail.isFetching}
                />
              ) : run ? (
                <>
                  <RunResult flowId={flowId} run={run} steps={stepViews} />
                  <RunOtherFiles flowId={flowId} run={run} />
                </>
              ) : (
                <LoadingState rows={2} />
              )}
            </Section>
            {stepsSection}
            {transcriptViews}
            {run?.evidence_access.can_read_evidence && searchedKnowledge(stepViews) ? (
              <FoldSection title={t("flow_runs_knowledge_heading")}>
                <RunKnowledge
                  flowId={flowId}
                  runId={runId}
                  steps={stepViews}
                  runSettled={settled}
                />
              </FoldSection>
            ) : null}
            {run ? (
              <>
                <FoldSection title={t("flow_runs_form_answers_heading")}>
                  <RunInput flow={flow} run={run} />
                </FoldSection>
                {run.token_usage || run.transcription_usage ? (
                  <FoldSection title={t("flow_runs_usage_heading")}>
                    <RunUsage run={run} />
                  </FoldSection>
                ) : null}
                {run.webhook_deliveries.length > 0 ? (
                  // Open while a delivery has not landed or was given up: that is what the run waits on.
                  <FoldSection
                    title={t("flow_run_extras_webhook_heading")}
                    defaultIsOpen={run.webhook_deliveries.some(
                      (delivery) => delivery.delivery_status !== "delivered"
                    )}
                  >
                    <RunWebhookDeliveries
                      deliveries={run.webhook_deliveries}
                      stepName={(order) =>
                        stepTitle(
                          stepViews.find((step) => step.order === order) ?? { order, label: "" },
                          t
                        )
                      }
                    />
                  </FoldSection>
                ) : null}
              </>
            ) : null}
            {summary ? (
              // The support ids are for support, not the first screen: with the evidence, or,
              // for someone who may not read it, under their own fold.
              <FoldSection
                title={
                  run?.evidence_access.can_read_evidence
                    ? t("flow_run_extras_trace_heading")
                    : t("flow_run_extras_failure_technical")
                }
              >
                <div className="flex flex-col gap-4">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                    <RunId
                      label={t("flow_run_more_run_id")}
                      value={summary.id}
                      hint={t("flow_run_more_run_id_hint")}
                    />
                    <RunId
                      label={t("flow_run_more_trace_id")}
                      value={summary.trace_id}
                      hint={t("flow_run_more_trace_id_hint")}
                    />
                  </div>
                  <RunTrace
                    flow={flow}
                    summary={summary}
                    steps={stepViews}
                    access={run?.evidence_access}
                    headingHidden
                  />
                </div>
              </FoldSection>
            ) : null}
          </>
        )}
      </div>
      <FlowRunStarter flowId={flowId} open={starting} onOpenChange={setStarting} />
    </div>
  );
}
