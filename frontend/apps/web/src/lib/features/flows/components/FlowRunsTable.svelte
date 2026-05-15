<script lang="ts">
  import {
    IntricError,
    type Flow,
    type FlowRun,
    type FlowRunResultFile,
    type Intric
  } from "@intric/intric-js";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import FlowRunEvidence from "./FlowRunEvidence.svelte";
  import FlowRunProgressPanel from "./FlowRunProgressPanel.svelte";
  import FlowRunReviewCheckpointPanel from "./FlowRunReviewCheckpointPanel.svelte";
  import FlowRunResultFileButton from "./FlowRunResultFileButton.svelte";
  import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";
  import FlowRunTokenUsageBadge from "./FlowRunTokenUsageBadge.svelte";
  import { toast } from "$lib/components/toast";
  import { getFlowRunStatusLabel } from "./flowRunStatusLabel";
  import { getRedispatchToastKind } from "./flowRunRedispatchFeedback";
  import { m } from "$lib/paraglide/messages";
  import type { FlowRunProgressSnapshot } from "./flowRunProgress";
  import {
    getConfirmedOptimisticFlowRunIds,
    mergeOptimisticFlowRuns,
    shouldAutoFocusOptimisticFlowRun
  } from "./flowRunsOptimistic";
  import {
    canRedispatchFlowRun,
    FLOW_RUN_STATUS_FILTER_OPTIONS,
    isFlowRunActive,
    isFlowRunAwaitingReview,
    isFlowRunCancellable,
    shouldPollFlowRunStatus,
    type FlowRunStatus,
    type FlowRunStatusFilter
  } from "./flowRunStatusSets";
  import { getActiveFlowRunId, shouldAutoFocusFlowRun } from "./flowRunsFocus";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import type { FlowCareDataPolicy } from "$lib/features/flows/flowCareDataPolicy";
  import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";
  import FlowRunErrorAlert from "./FlowRunErrorAlert.svelte";
  import {
    createFlowRunHistoryState,
    destroyFlowRunHistoryPolling,
    loadFlowRunHistory,
    syncFlowRunHistoryFlow,
    syncFlowRunHistoryPolling,
    syncFlowRunHistoryReload
  } from "./flowRunHistoryState";

  let {
    flow,
    careDataPolicy = undefined,
    eneo,
    visible = true,
    optimisticRuns = [],
    reloadTrigger = 0,
    latestRunPayload = $bindable(null),
    onOptimisticRunsConfirmed
  }: {
    flow: Flow;
    careDataPolicy?: FlowCareDataPolicy;
    eneo: Intric;
    visible?: boolean;
    optimisticRuns?: FlowRun[];
    reloadTrigger?: number;
    latestRunPayload?: Record<string, unknown> | null;
    onOptimisticRunsConfirmed?: (runIds: string[]) => void;
  } = $props();

  let history = $state(createFlowRunHistoryState());
  let selectedRunId: string | null = $state(null);

  type SortKey = "started" | "duration" | "status";
  type SortDir = "asc" | "desc";
  let statusFilter: FlowRunStatusFilter = $state(null);
  let sortKey: SortKey = $state("started");
  let sortDir: SortDir = $state("desc");

  const userMode = getFlowUserMode();
  const showAdvancedControls = $derived($userMode === "power_user");
  const historyTableColumnCount = 6;
  const historyModeDescription = $derived(
    showAdvancedControls ? m.flow_history_power_user_mode_desc() : m.flow_history_user_mode_desc()
  );

  const statusCounts = $derived.by(() => {
    const counts: Record<FlowRunStatus, number> = {
      completed: 0,
      failed: 0,
      running: 0,
      queued: 0,
      awaiting_review: 0,
      cancelled: 0
    };
    for (const r of history.runs) {
      counts[r.status]++;
    }
    return counts;
  });

  const statusTranslations = {
    completed: m.flow_run_status_completed,
    failed: m.flow_run_status_failed,
    queued: m.flow_run_status_queued,
    running: m.flow_run_status_running,
    awaiting_review: m.flow_run_status_awaiting_review,
    cancelled: m.flow_run_status_cancelled
  };

  function getRunStatusLabel(status: string): string {
    return getFlowRunStatusLabel(status, statusTranslations);
  }

  function runDurationMs(run: FlowRun): number {
    const startRaw = run.started_at ?? run.created_at;
    const finishRaw = run.finished_at;
    if (!startRaw || !finishRaw) return -1;
    const start = new Date(startRaw).getTime();
    const finish = new Date(finishRaw).getTime();
    if (Number.isNaN(start) || Number.isNaN(finish)) return -1;
    return finish - start;
  }

  const visibleRuns = $derived.by(() => {
    const filtered = statusFilter
      ? history.runs.filter((r) => r.status === statusFilter)
      : history.runs;
    const sorted = [...filtered].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "started") {
        cmp =
          new Date(a.started_at ?? a.created_at ?? 0).getTime() -
          new Date(b.started_at ?? b.created_at ?? 0).getTime();
      } else if (sortKey === "duration") {
        cmp = runDurationMs(a) - runDurationMs(b);
      } else {
        cmp = a.status.localeCompare(b.status);
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  });

  // mergeOptimisticFlowRuns returns the original array when no merge is needed, which keeps
  // this self-writing effect from looping after the backend list catches up.
  $effect(() => {
    const nextRuns = mergeOptimisticFlowRuns(history.runs, optimisticRuns);
    if (nextRuns === history.runs) return;

    history.runs = nextRuns;
    const newestOptimisticRun = optimisticRuns[0];
    if (shouldAutoFocusOptimisticFlowRun(newestOptimisticRun, lastOptimisticAutoFocusedRunId)) {
      selectedRunId = newestOptimisticRun.id;
      lastOptimisticAutoFocusedRunId = newestOptimisticRun.id;
      latestRunPayload = newestOptimisticRun.input_payload_json ?? latestRunPayload;
    }
  });

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortKey = key;
      sortDir = key === "status" ? "asc" : "desc";
    }
  }

  function ariaSortFor(key: SortKey): "ascending" | "descending" | "none" {
    if (sortKey !== key) return "none";
    return sortDir === "asc" ? "ascending" : "descending";
  }
  let redispatchingRunId: string | null = $state(null);
  let cancellingRunId: string | null = $state(null);
  let showCancelConfirm = $state(false);
  let pendingCancelRunId: string | null = $state(null);
  let progressSnapshotsByRunId = $state<Record<string, FlowRunProgressSnapshot>>({});
  let lastAutoFocusedRunId: string | null = $state(null);
  let lastOptimisticAutoFocusedRunId: string | null = $state(null);

  async function loadRuns() {
    const result = await loadFlowRunHistory(history, {
      flowId: flow?.id,
      listRuns: async (flowId) => eneo.flows.runs.list({ flowId }),
      getErrorMessage: (error) =>
        error instanceof IntricError
          ? getFlowRuntimeErrorMessage(error, error.getReadableMessage())
          : error instanceof Error
            ? error.message
            : m.flow_history_load_failed_desc()
    });

    if (result.kind === "loaded") {
      const nextRuns = result.runs;
      const confirmedOptimisticRunIds = getConfirmedOptimisticFlowRunIds(nextRuns, optimisticRuns);
      if (confirmedOptimisticRunIds.length > 0) {
        onOptimisticRunsConfirmed?.(confirmedOptimisticRunIds);
      }
      latestRunPayload =
        history.runs.length > 0 ? (history.runs[0].input_payload_json ?? null) : null;
      const activeRunId = getActiveFlowRunId(nextRuns);
      if (
        activeRunId &&
        shouldAutoFocusFlowRun({
          runs: nextRuns,
          activeRunId,
          selectedRunId,
          lastAutoFocusedRunId
        })
      ) {
        selectedRunId = activeRunId;
        lastAutoFocusedRunId = activeRunId;
      }
    } else if (result.kind === "failed") {
      console.error("Error loading flow runs", result.error);
    }
  }

  $effect(() => {
    if (syncFlowRunHistoryFlow(history, flow?.id)) {
      void loadRuns();
    }
  });

  $effect(() => {
    if (syncFlowRunHistoryReload(history, reloadTrigger)) {
      untrack(() => {
        void loadRuns();
      });
    }
  });

  let hasRunsToPoll = $derived(history.runs.some((r) => shouldPollFlowRunStatus(r.status)));

  $effect(() => {
    syncFlowRunHistoryPolling(history, {
      visible: () => visible,
      hasRunsToPoll: () => hasRunsToPoll,
      loadRuns
    });
  });

  $effect(() => {
    return () => {
      destroyFlowRunHistoryPolling(history);
    };
  });

  function formatDuration(start: string, end: string): string {
    const ms = new Date(end).getTime() - new Date(start).getTime();
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  }

  async function downloadArtifact(runId: string, fileId: string) {
    try {
      const { url } = await eneo.flows.runs.artifactSignedUrl({
        flowId: flow.id,
        runId,
        fileId,
        contentDisposition: "attachment"
      });
      window.open(url, "_blank");
    } catch (e) {
      console.error("Failed to download artifact", e);
      toast.error(m.flow_run_download_artifact_failed());
    }
  }

  async function redispatchRun(runId: string) {
    redispatchingRunId = runId;
    try {
      const result = await eneo.flows.runs.redispatch({ id: runId, flowId: flow.id });
      if (getRedispatchToastKind(result?.redispatched_count) === "success") {
        toast.success(m.flow_run_redispatch_requested());
      } else {
        toast.info(m.flow_run_redispatch_noop());
      }
      await loadRuns();
    } catch (error) {
      console.error("Failed to redispatch run", error);
      toast.error(m.flow_run_redispatch_failed());
    } finally {
      redispatchingRunId = null;
    }
  }

  function requestCancelRun(runId: string) {
    pendingCancelRunId = runId;
    showCancelConfirm = true;
  }

  async function confirmCancelRun() {
    if (!pendingCancelRunId) return;
    const runId = pendingCancelRunId;
    showCancelConfirm = false;
    pendingCancelRunId = null;
    cancellingRunId = runId;
    try {
      await eneo.flows.runs.cancel({ id: runId, flowId: flow.id });
      toast.success(m.flow_run_cancel_requested());
      await loadRuns();
    } catch (error) {
      console.error("Failed to cancel run", error);
      toast.error(m.flow_run_cancel_failed());
    } finally {
      cancellingRunId = null;
    }
  }

  function getEvidenceRowId(runId: string): string {
    return `flow-run-evidence-${runId}`;
  }

  function toggleRunDetails(runId: string) {
    selectedRunId = selectedRunId === runId ? null : runId;
  }

  function updateProgressSnapshot(runId: string, snapshot: FlowRunProgressSnapshot) {
    progressSnapshotsByRunId = {
      ...progressSnapshotsByRunId,
      [runId]: snapshot
    };
  }

  function handleReviewCheckpointChanged() {
    void loadRuns();
  }

  function getPrimaryResultFile(resultFiles: FlowRunResultFile[]): FlowRunResultFile | null {
    return resultFiles.find((file) => file.availability === "available") ?? resultFiles[0] ?? null;
  }

  function getRunErrorMessage(run: FlowRun): string | null {
    return run.error?.message ?? null;
  }
</script>

{#snippet failedRunAlert(run: FlowRun)}
  {@const errorMessage = getRunErrorMessage(run)}
  {#if errorMessage}
    <FlowRunErrorAlert error={run.error} message={errorMessage} steps={flow.steps} />
  {/if}
{/snippet}

<section class="mx-auto flex w-full max-w-[1400px] flex-col gap-4 px-3 py-4 sm:px-6 sm:py-6">
  <header>
    <div class="min-w-0">
      <h2 class="text-primary text-base font-semibold tracking-tight sm:text-lg">
        {m.flow_history()}
      </h2>
      <p class="text-secondary mt-1 max-w-2xl text-sm leading-relaxed">
        {historyModeDescription}
      </p>
    </div>
  </header>

  {#if history.loading}
    <div class="text-muted flex items-center justify-center gap-2 py-10 text-sm">
      <IconLoadingSpinner class="size-4 animate-spin" />
      {m.flow_loading()}
    </div>
  {:else if history.loadError}
    <Alert.Root variant="destructive">
      <Alert.Title>{m.flow_history_load_failed_title()}</Alert.Title>
      <Alert.Description>
        <span>{m.flow_history_load_failed_desc()}</span>
        <span class="mt-1 block text-xs break-words opacity-80">{history.loadError}</span>
      </Alert.Description>
      <Alert.Action>
        <Button variant="outline" size="sm" onclick={loadRuns}>
          {m.flow_retry()}
        </Button>
      </Alert.Action>
    </Alert.Root>
  {:else if history.runs.length === 0}
    <div
      class="border-default bg-primary rounded-xl border py-14 text-center"
      aria-label={m.flow_no_runs_yet()}
    >
      <p class="text-muted text-sm">{m.flow_no_runs_yet()}</p>
    </div>
  {:else}
    {#if showAdvancedControls}
      <div class="mb-3 flex flex-wrap items-center gap-1.5" role="group" aria-label={m.filter()}>
        <button
          type="button"
          class="border-default focus-visible:ring-accent-default/30 inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-[0.8rem] font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none {statusFilter ===
          null
            ? 'bg-accent-default/10 border-accent-default/30 text-accent-stronger'
            : 'text-secondary hover:bg-hover-dimmer hover:text-primary'}"
          aria-pressed={statusFilter === null}
          onclick={() => (statusFilter = null)}
        >
          {m.all_categories()}
          <span class="text-muted tabular-nums">{history.runs.length}</span>
        </button>
        {#each FLOW_RUN_STATUS_FILTER_OPTIONS as status (status)}
          {@const count = statusCounts[status] ?? 0}
          {#if count > 0}
            <button
              type="button"
              class="border-default focus-visible:ring-accent-default/30 inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-[0.8rem] font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none {statusFilter ===
              status
                ? 'bg-accent-default/10 border-accent-default/30 text-accent-stronger'
                : 'text-secondary hover:bg-hover-dimmer hover:text-primary'}"
              aria-pressed={statusFilter === status}
              onclick={() => (statusFilter = statusFilter === status ? null : status)}
            >
              {getRunStatusLabel(status)}
              <span class="text-muted tabular-nums">{count}</span>
            </button>
          {/if}
        {/each}
      </div>
    {/if}

    {#if visibleRuns.length === 0}
      <div
        class="border-default bg-primary flex flex-col items-center gap-3 rounded-xl border py-14 text-center"
        role="status"
      >
        <p class="text-muted text-sm">{m.flow_no_runs_yet()}</p>
        <Button variant="outline" size="sm" onclick={() => (statusFilter = null)}>
          {m.clear()}
        </Button>
      </div>
    {:else}
      <!-- Desktop: Table -->
      <div
        class="border-default bg-primary hidden overflow-hidden rounded-xl border shadow-xs md:block"
      >
        <Table.Root>
          <Table.Header>
            <Table.Row class="border-default hover:bg-transparent">
              <Table.Head
                aria-sort={showAdvancedControls ? ariaSortFor("status") : undefined}
                class="text-muted h-11 px-0 text-xs font-medium tracking-wide uppercase"
              >
                {#if showAdvancedControls}
                  <button
                    type="button"
                    class="text-muted hover:text-primary focus-visible:ring-accent-default/30 inline-flex h-11 w-full items-center gap-1 px-4 text-left text-xs font-medium tracking-wide uppercase transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset"
                    onclick={() => toggleSort("status")}
                  >
                    {m.status()}
                    {#if sortKey === "status"}
                      <IconChevronDown
                        class="size-3 transition-transform {sortDir === 'asc' ? 'rotate-180' : ''}"
                        aria-hidden="true"
                      />
                    {/if}
                  </button>
                {:else}
                  <span class="block px-4">{m.status()}</span>
                {/if}
              </Table.Head>
              <Table.Head
                class="text-muted hidden h-11 px-4 text-xs font-medium tracking-wide uppercase lg:table-cell"
              >
                {m.version()}
              </Table.Head>
              <Table.Head
                aria-sort={showAdvancedControls ? ariaSortFor("started") : undefined}
                class="text-muted h-11 px-0 text-xs font-medium tracking-wide uppercase"
              >
                {#if showAdvancedControls}
                  <button
                    type="button"
                    class="text-muted hover:text-primary focus-visible:ring-accent-default/30 inline-flex h-11 w-full items-center gap-1 px-4 text-left text-xs font-medium tracking-wide uppercase transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset"
                    onclick={() => toggleSort("started")}
                  >
                    {m.flow_run_started()}
                    {#if sortKey === "started"}
                      <IconChevronDown
                        class="size-3 transition-transform {sortDir === 'asc' ? 'rotate-180' : ''}"
                        aria-hidden="true"
                      />
                    {/if}
                  </button>
                {:else}
                  <span class="block px-4">{m.flow_run_started()}</span>
                {/if}
              </Table.Head>
              <Table.Head
                aria-sort={showAdvancedControls ? ariaSortFor("duration") : undefined}
                class="text-muted hidden h-11 px-0 text-xs font-medium tracking-wide uppercase lg:table-cell"
              >
                {#if showAdvancedControls}
                  <button
                    type="button"
                    class="text-muted hover:text-primary focus-visible:ring-accent-default/30 inline-flex h-11 w-full items-center gap-1 px-4 text-left text-xs font-medium tracking-wide uppercase transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset"
                    onclick={() => toggleSort("duration")}
                  >
                    {m.duration()}
                    {#if sortKey === "duration"}
                      <IconChevronDown
                        class="size-3 transition-transform {sortDir === 'asc' ? 'rotate-180' : ''}"
                        aria-hidden="true"
                      />
                    {/if}
                  </button>
                {:else}
                  <span class="block px-4">{m.duration()}</span>
                {/if}
              </Table.Head>
              <Table.Head
                class="text-muted hidden h-11 px-4 text-xs font-medium tracking-wide uppercase lg:table-cell"
              >
                {m.flow_run_tokens()}
              </Table.Head>
              <Table.Head
                class="text-muted h-11 px-4 text-right text-xs font-medium tracking-wide uppercase"
              >
                <span class="sr-only">{m.actions()}</span>
              </Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each visibleRuns as run (run.id)}
              {@const isExpanded = selectedRunId === run.id}
              <Table.Row
                class="border-default hover:bg-muted/40 cursor-pointer transition-colors {isExpanded
                  ? 'bg-muted/50'
                  : ''}"
                tabindex={0}
                onclick={() => toggleRunDetails(run.id)}
                onkeydown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggleRunDetails(run.id);
                  }
                }}
              >
                <Table.Cell class="px-4 py-3 align-middle">
                  <FlowRunStatusBadge status={run.status} />
                </Table.Cell>
                <Table.Cell
                  class="text-secondary hidden px-4 py-3 align-middle tabular-nums lg:table-cell"
                >
                  v{run.flow_version}
                </Table.Cell>
                <Table.Cell class="text-secondary px-4 py-3 align-middle tabular-nums">
                  {new Date(run.created_at).toLocaleString()}
                </Table.Cell>
                <Table.Cell
                  class="text-secondary hidden px-4 py-3 align-middle tabular-nums lg:table-cell"
                >
                  {#if run.status === "completed" || run.status === "failed"}
                    {formatDuration(run.created_at, run.updated_at)}
                  {:else if run.status === "running"}
                    <span class="text-accent-stronger">{m.flow_run_running()}</span>
                  {:else if isFlowRunAwaitingReview(run.status)}
                    <span class="text-accent-stronger">{getRunStatusLabel(run.status)}</span>
                  {:else}
                    —
                  {/if}
                </Table.Cell>
                <!-- eslint-disable-next-line a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                <Table.Cell
                  class="hidden px-4 py-3 align-middle lg:table-cell"
                  onclick={(e: MouseEvent) => e.stopPropagation()}
                >
                  <FlowRunTokenUsageBadge tokenUsage={run.token_usage} emptyPlaceholder />
                </Table.Cell>
                <!-- eslint-disable-next-line a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                <Table.Cell
                  class="px-2 py-2 text-right align-middle"
                  onclick={(e: MouseEvent) => e.stopPropagation()}
                >
                  <div class="inline-flex items-center gap-1">
                    {#if run.status === "completed"}
                      {@const resultFiles = run.result_files ?? []}
                      {@const primaryResultFile = getPrimaryResultFile(resultFiles)}
                      {#if primaryResultFile}
                        <FlowRunResultFileButton
                          compact
                          file={primaryResultFile}
                          extraCount={Math.max(resultFiles.length - 1, 0)}
                          onDownload={(fileId) => downloadArtifact(run.id, fileId)}
                        />
                      {/if}
                    {/if}
                    <Button
                      variant="outline"
                      size="sm"
                      aria-expanded={isExpanded}
                      aria-controls={getEvidenceRowId(run.id)}
                      onclick={() => toggleRunDetails(run.id)}
                    >
                      {m.flow_run_evidence()}
                      <IconChevronDown
                        data-icon="inline-end"
                        class="transition-transform duration-200 {isExpanded ? 'rotate-180' : ''}"
                      />
                    </Button>
                    {#if canRedispatchFlowRun(run.status)}
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={redispatchingRunId === run.id}
                        onclick={() => void redispatchRun(run.id)}
                      >
                        {redispatchingRunId === run.id
                          ? m.flow_run_redispatching()
                          : m.flow_run_redispatch()}
                      </Button>
                    {/if}
                    {#if isFlowRunCancellable(run.status)}
                      <Button
                        variant="destructive"
                        size="sm"
                        disabled={cancellingRunId === run.id}
                        onclick={() => requestCancelRun(run.id)}
                      >
                        {cancellingRunId === run.id ? m.flow_run_cancelling() : m.cancel()}
                      </Button>
                    {/if}
                  </div>
                </Table.Cell>
              </Table.Row>
              {#if run.status === "failed" && getRunErrorMessage(run)}
                <Table.Row class="border-default hover:bg-transparent">
                  <Table.Cell colspan={historyTableColumnCount} class="px-4 py-2">
                    {@render failedRunAlert(run)}
                  </Table.Cell>
                </Table.Row>
              {/if}
              {#if isExpanded}
                <Table.Row class="border-default hover:bg-transparent">
                  <Table.Cell
                    id={getEvidenceRowId(run.id)}
                    colspan={historyTableColumnCount}
                    class="bg-muted/30 px-3 py-4"
                  >
                    {#if isFlowRunActive(run.status)}
                      <FlowRunProgressPanel
                        runId={run.id}
                        flowId={flow.id}
                        {eneo}
                        runStatus={run.status}
                        runStartedAt={run.started_at ?? run.created_at}
                        initialSnapshot={progressSnapshotsByRunId[run.id] ?? null}
                        onSnapshotUpdate={(snapshot) => updateProgressSnapshot(run.id, snapshot)}
                      />
                    {:else if isFlowRunAwaitingReview(run.status)}
                      <FlowRunReviewCheckpointPanel
                        runId={run.id}
                        flowId={flow.id}
                        {eneo}
                        onChanged={handleReviewCheckpointChanged}
                      />
                    {:else}
                      <FlowRunEvidence
                        runId={run.id}
                        flowId={flow.id}
                        sensitiveCareDataFlow={careDataPolicy?.sensitive === true}
                        {eneo}
                        runStatus={run.status}
                        fallbackSnapshot={progressSnapshotsByRunId[run.id] ?? null}
                      />
                    {/if}
                  </Table.Cell>
                </Table.Row>
              {/if}
            {/each}
          </Table.Body>
        </Table.Root>
      </div>

      <!-- Mobile: stacked card list -->
      <ul class="flex flex-col gap-2 md:hidden" aria-label={m.flow_history()}>
        {#each visibleRuns as run (run.id)}
          {@const isExpanded = selectedRunId === run.id}
          <li class="border-default bg-primary rounded-xl border">
            <button
              type="button"
              class="focus-visible:ring-ring/40 flex w-full flex-col gap-2 rounded-xl px-4 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-inset"
              aria-expanded={isExpanded}
              aria-controls={getEvidenceRowId(run.id)}
              onclick={() => toggleRunDetails(run.id)}
            >
              <div class="flex items-center justify-between gap-2">
                <FlowRunStatusBadge status={run.status} />
                <Badge variant="outline" class="h-5 shrink-0 text-xs font-medium tabular-nums">
                  v{run.flow_version}
                </Badge>
              </div>
              <div class="flex items-center justify-between gap-2">
                <p class="text-secondary truncate text-sm tabular-nums">
                  {new Date(run.created_at).toLocaleString()}
                </p>
                <div class="flex shrink-0 items-center gap-1.5">
                  <FlowRunTokenUsageBadge tokenUsage={run.token_usage} interactive={false} />
                  {#if run.status === "completed" || run.status === "failed"}
                    <p class="text-muted text-xs tabular-nums">
                      {formatDuration(run.created_at, run.updated_at)}
                    </p>
                  {:else if isFlowRunAwaitingReview(run.status)}
                    <p class="text-accent-stronger text-xs">
                      {getRunStatusLabel(run.status)}
                    </p>
                  {/if}
                </div>
              </div>
            </button>
            {#if run.status === "failed" && getRunErrorMessage(run)}
              <div class="border-default border-t px-3 py-3">
                {@render failedRunAlert(run)}
              </div>
            {/if}
            {#if isFlowRunCancellable(run.status)}
              <div class="border-default flex items-center gap-2 border-t px-4 py-2">
                {#if canRedispatchFlowRun(run.status)}
                  <Button
                    variant="outline"
                    size="sm"
                    class="flex-1"
                    disabled={redispatchingRunId === run.id}
                    onclick={() => void redispatchRun(run.id)}
                  >
                    {redispatchingRunId === run.id
                      ? m.flow_run_redispatching()
                      : m.flow_run_redispatch()}
                  </Button>
                {/if}
                <Button
                  variant="destructive"
                  size="sm"
                  class="flex-1"
                  disabled={cancellingRunId === run.id}
                  onclick={() => requestCancelRun(run.id)}
                >
                  {cancellingRunId === run.id ? m.flow_run_cancelling() : m.cancel()}
                </Button>
              </div>
            {/if}
            {#if isExpanded}
              <div
                id={getEvidenceRowId(run.id)}
                class="border-default bg-muted/30 border-t px-3 py-3"
              >
                {#if isFlowRunActive(run.status)}
                  <FlowRunProgressPanel
                    runId={run.id}
                    flowId={flow.id}
                    {eneo}
                    runStatus={run.status}
                    runStartedAt={run.started_at ?? run.created_at}
                    initialSnapshot={progressSnapshotsByRunId[run.id] ?? null}
                    onSnapshotUpdate={(snapshot) => updateProgressSnapshot(run.id, snapshot)}
                  />
                {:else if isFlowRunAwaitingReview(run.status)}
                  <FlowRunReviewCheckpointPanel
                    runId={run.id}
                    flowId={flow.id}
                    {eneo}
                    onChanged={handleReviewCheckpointChanged}
                  />
                {:else}
                  <FlowRunEvidence
                    runId={run.id}
                    flowId={flow.id}
                    {eneo}
                    runStatus={run.status}
                    fallbackSnapshot={progressSnapshotsByRunId[run.id] ?? null}
                  />
                {/if}
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<AlertDialog.Root bind:open={showCancelConfirm}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.flow_run_cancel_title()}</AlertDialog.Title>
      <AlertDialog.Description>{m.flow_run_cancel_confirm()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.flow_run_cancel_keep_running()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={confirmCancelRun}>
        {m.flow_run_cancel_action()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
