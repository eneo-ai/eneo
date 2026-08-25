<script lang="ts">
  import {
    EneoError,
    type Eneo,
    type Flow,
    type FlowRun,
    type FlowRunResultFile
  } from "@eneo/eneo-js";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import FlowRunEvidence from "./FlowRunEvidence.svelte";
  import FlowRunProgressPanel from "./FlowRunProgressPanel.svelte";
  import FlowRunReviewCheckpointPanel from "./FlowRunReviewCheckpointPanel.svelte";
  import FlowRunResultFileButton from "./FlowRunResultFileButton.svelte";
  import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";
  import FlowRunTokenUsageBadge from "./FlowRunTokenUsageBadge.svelte";
  import FlowRunTranscriptionUsageBadge from "./FlowRunTranscriptionUsageBadge.svelte";
  import { getLocale } from "$lib/paraglide/runtime";
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
    type FlowRunStatusFilter
  } from "./flowRunStatusSets";
  import { getActiveFlowRunId, shouldAutoFocusFlowRun } from "./flowRunsFocus";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { IsMobile } from "$lib/hooks/is-mobile.svelte";
  import type { FlowCareDataPolicy } from "$lib/features/flows/flowCareDataPolicy";
  import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";
  import FlowRunErrorAlert from "./FlowRunErrorAlert.svelte";
  import {
    createFlowRunHistoryState,
    destroyFlowRunHistoryPolling,
    MAX_LOADED_FLOW_RUNS,
    loadFlowRunHistory,
    syncFlowRunHistoryFlow,
    syncFlowRunHistoryPolling,
    syncFlowRunHistoryReload
  } from "./flowRunHistoryState";
  import {
    DEFAULT_FLOW_RUN_HISTORY_SORT,
    createFlowRunStatusCounts,
    filterFlowRuns,
    primeFlowRunInputSearchText,
    getFlowRunHistoryAriaSort,
    nextFlowRunHistorySortState,
    sortFlowRuns,
    type FlowRunHistorySortKey,
    type FlowRunHistorySortState
  } from "./flowRunHistoryPresentation";

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
    eneo: Eneo;
    visible?: boolean;
    optimisticRuns?: FlowRun[];
    reloadTrigger?: number;
    latestRunPayload?: Record<string, unknown> | null;
    onOptimisticRunsConfirmed?: (runIds: string[]) => void;
  } = $props();

  let history = $state(createFlowRunHistoryState());
  let selectedRunId: string | null = $state(null);

  let statusFilter: FlowRunStatusFilter = $state(null);
  let searchQuery = $state("");
  const uid = $props.id();
  const searchScopeHintId = `${uid}-history-search-scope`;

  // The expanded detail module mounts exactly once per run: a double mount
  // duplicates ids, aria-controls targets, and the evidence request. The
  // existing IsMobile owner decides which tree carries it.
  const mobileViewport = new IsMobile();

  const windowFull = $derived(history.runs.length >= MAX_LOADED_FLOW_RUNS);
  const canLoadMore = $derived(history.hasMore && !windowFull);

  // DOM budget: at most RENDERED_RUNS_PAGE_SIZE rows mount per expansion —
  // reconciliation of a thousand-row tree is what makes keystrokes slow,
  // not the filter itself. Any projection change resets the budget.
  const RENDERED_RUNS_PAGE_SIZE = 100;
  let renderLimit = $state(RENDERED_RUNS_PAGE_SIZE);
  $effect(() => {
    void searchQuery;
    void statusFilter;
    void sortState;
    void flow?.id;
    renderLimit = RENDERED_RUNS_PAGE_SIZE;
  });

  async function loadMoreRuns() {
    await loadRuns("more");
  }
  let sortState: FlowRunHistorySortState = $state(DEFAULT_FLOW_RUN_HISTORY_SORT);

  const userMode = getFlowUserMode();
  const showAdvancedControls = $derived($userMode === "power_user");
  // Tokens column only exists in Avancerad, so the expanded-row colspan follows.
  const historyTableColumnCount = $derived(showAdvancedControls ? 6 : 5);
  const historyModeDescription = $derived(
    showAdvancedControls ? m.flow_history_power_user_mode_desc() : m.flow_history_user_mode_desc()
  );

  // Optimistic rows are a DERIVED display overlay — they are never written
  // into history.runs, so the pagination state only ever sees
  // backend-confirmed ids (a fake id would otherwise anchor refresh
  // contiguity and hide real rows).
  const displayRuns = $derived(mergeOptimisticFlowRuns(history.runs, optimisticRuns));

  const statusCounts = $derived(createFlowRunStatusCounts(displayRuns));

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

  function getRunVersionLabel(run: FlowRun): string {
    return `v${run.flow_version}`;
  }

  // Sorting is derived separately so a search keystroke only re-filters.
  const sortedRuns = $derived(sortFlowRuns(displayRuns, sortState));
  const visibleRuns = $derived(
    filterFlowRuns(sortedRuns, {
      statusFilter,
      searchQuery,
      labels: {
        labelsKey: getLocale(),
        getStatusLabel: getRunStatusLabel,
        getDateLabel: (run) => new Date(run.created_at).toLocaleString(getLocale())
      }
    })
  );
  const renderedRuns = $derived(visibleRuns.slice(0, renderLimit));
  const hasHiddenMatches = $derived(visibleRuns.length > renderLimit);

  $effect(() => {
    const newestOptimisticRun = optimisticRuns[0];
    if (shouldAutoFocusOptimisticFlowRun(newestOptimisticRun, lastOptimisticAutoFocusedRunId)) {
      selectedRunId = newestOptimisticRun.id;
      lastOptimisticAutoFocusedRunId = newestOptimisticRun.id;
      latestRunPayload = newestOptimisticRun.input_payload_json ?? latestRunPayload;
    }
  });

  function toggleSort(key: FlowRunHistorySortKey) {
    sortState = nextFlowRunHistorySortState(sortState, key);
  }

  function ariaSortFor(key: FlowRunHistorySortKey): "ascending" | "descending" | "none" {
    return getFlowRunHistoryAriaSort(sortState, key);
  }
  let redispatchingRunId: string | null = $state(null);
  let cancellingRunId: string | null = $state(null);
  let showCancelConfirm = $state(false);
  let pendingCancelRunId: string | null = $state(null);
  let progressSnapshotsByRunId = $state<Record<string, FlowRunProgressSnapshot>>({});
  let lastAutoFocusedRunId: string | null = $state(null);
  let lastOptimisticAutoFocusedRunId: string | null = $state(null);

  async function loadRuns(mode: "refresh" | "more" = "refresh") {
    const result = await loadFlowRunHistory(history, {
      flowId: flow?.id,
      mode,
      listRuns: async (flowId, page) =>
        eneo.flows.runs.list({ flowId, limit: page.limit, offset: page.offset }),
      pollableRefresh: {
        getRun: async (flowId, runId) => eneo.flows.runs.get({ id: runId, flowId }),
        shouldPollRun: (run) => shouldPollFlowRunStatus(run.status)
      },
      getErrorMessage: (error) =>
        error instanceof EneoError
          ? getFlowRuntimeErrorMessage(error, error.getReadableMessage())
          : error instanceof Error
            ? error.message
            : m.flow_history_load_failed_desc()
    });

    if (result.kind === "loaded") {
      // Hostile input payloads pay their enumeration cost off the keystroke
      // path, batched through the task queue so page load never blocks on
      // it either. Priming is an optimization only: the search cache also
      // fills lazily on a miss.
      const toPrime = [...result.runs];
      const primeBatch = () => {
        for (const loadedRun of toPrime.splice(0, 25)) {
          primeFlowRunInputSearchText(loadedRun);
        }
        if (toPrime.length > 0) setTimeout(primeBatch, 0);
      };
      setTimeout(primeBatch, 0);
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
      // The window reset is atomic: the filters belong to the old flow's
      // rows, so they clear together with the loaded runs.
      searchQuery = "";
      statusFilter = null;
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

  let hasRunsToPoll = $derived(displayRuns.some((r) => shouldPollFlowRunStatus(r.status)));

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

  async function redispatchRun(run: FlowRun) {
    redispatchingRunId = run.id;
    try {
      const result = await eneo.flows.runs.redispatch({
        id: run.id,
        flowId: flow.id,
        expected_dispatch_exhausted_at: run.dispatch_exhausted_at
      });
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

{#snippet stepRunDetail(run: FlowRun)}
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
{/snippet}

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
        <Button variant="outline" size="sm" onclick={() => void loadRuns()}>
          {m.flow_retry()}
        </Button>
      </Alert.Action>
    </Alert.Root>
  {:else if displayRuns.length === 0}
    <div
      class="border-default bg-primary rounded-xl border py-14 text-center"
      aria-label={m.flow_no_runs_yet()}
    >
      <p class="text-muted text-sm">{m.flow_no_runs_yet()}</p>
    </div>
  {:else}
    <div class="relative mb-2 max-w-md">
      <Input
        type="search"
        bind:value={searchQuery}
        placeholder={m.flow_history_search_placeholder()}
        aria-label={m.flow_history_search_placeholder()}
        aria-describedby={searchQuery ? searchScopeHintId : undefined}
        class="h-9"
      />
      {#if searchQuery}
        <p id={searchScopeHintId} class="text-muted mt-1 text-xs leading-relaxed">
          {windowFull
            ? m.flow_history_search_scope_hint_window_full({
                count: String(history.runs.length)
              })
            : m.flow_history_search_scope_hint({ count: String(history.runs.length) })}
        </p>
      {/if}
    </div>
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
        <span class="text-muted tabular-nums">{displayRuns.length}</span>
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

    {#if visibleRuns.length === 0}
      <div
        class="border-default bg-primary flex flex-col gap-3 rounded-xl border px-4 py-8 sm:px-6"
        role="status"
      >
        <p class="text-secondary text-sm">
          {searchQuery ? m.flow_history_no_search_matches() : m.flow_no_runs_yet()}
        </p>
        <div class="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onclick={() => {
              statusFilter = null;
              searchQuery = "";
            }}
          >
            {m.clear()}
          </Button>
          {#if canLoadMore}
            <Button
              variant="outline"
              size="sm"
              disabled={history.inFlightGeneration !== null}
              onclick={() => void loadMoreRuns()}
            >
              {history.loadMoreError ? m.flow_retry() : m.flow_history_load_more()}
            </Button>
          {:else if history.hasMore}
            <span class="text-muted text-xs"
              >{m.flow_history_window_full({
                count: MAX_LOADED_FLOW_RUNS.toLocaleString(getLocale())
              })}</span
            >
          {/if}
          {#if history.loadMoreError}
            <span class="text-negative-default text-xs" role="alert">
              {m.flow_history_load_more_failed()}
            </span>
          {/if}
        </div>
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
                    {#if sortState.key === "status"}
                      <IconChevronDown
                        class="size-3 transition-transform {sortState.dir === 'asc'
                          ? 'rotate-180'
                          : ''}"
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
                    {#if sortState.key === "started"}
                      <IconChevronDown
                        class="size-3 transition-transform {sortState.dir === 'asc'
                          ? 'rotate-180'
                          : ''}"
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
                    {#if sortState.key === "duration"}
                      <IconChevronDown
                        class="size-3 transition-transform {sortState.dir === 'asc'
                          ? 'rotate-180'
                          : ''}"
                        aria-hidden="true"
                      />
                    {/if}
                  </button>
                {:else}
                  <span class="block px-4">{m.duration()}</span>
                {/if}
              </Table.Head>
              {#if showAdvancedControls}
                <Table.Head
                  class="text-muted hidden h-11 px-4 text-xs font-medium tracking-wide uppercase lg:table-cell"
                >
                  {m.flow_run_tokens()}
                </Table.Head>
              {/if}
              <Table.Head
                class="text-muted h-11 px-4 text-right text-xs font-medium tracking-wide uppercase"
              >
                <span class="sr-only">{m.actions()}</span>
              </Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each renderedRuns as run (run.id)}
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
                  {getRunVersionLabel(run)}
                </Table.Cell>
                <Table.Cell class="text-secondary px-4 py-3 align-middle tabular-nums">
                  {new Date(run.created_at).toLocaleString(getLocale())}
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
                {#if showAdvancedControls}
                  <!-- eslint-disable-next-line a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                  <Table.Cell
                    class="hidden px-4 py-3 align-middle lg:table-cell"
                    onclick={(e: MouseEvent) => e.stopPropagation()}
                  >
                    <div class="flex items-center gap-1.5">
                      <FlowRunTokenUsageBadge tokenUsage={run.token_usage} />
                      <FlowRunTranscriptionUsageBadge
                        transcriptionUsage={run.transcription_usage}
                      />
                    </div>
                  </Table.Cell>
                {/if}
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
                      data-testid={`flow-run-evidence-toggle-${run.id}`}
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
                        onclick={() => void redispatchRun(run)}
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
              {#if isExpanded && !mobileViewport.current}
                <Table.Row class="border-default hover:bg-transparent">
                  <Table.Cell
                    id={getEvidenceRowId(run.id)}
                    colspan={historyTableColumnCount}
                    class="bg-muted/30 px-3 py-4"
                  >
                    {@render stepRunDetail(run)}
                  </Table.Cell>
                </Table.Row>
              {/if}
            {/each}
          </Table.Body>
        </Table.Root>
      </div>

      <!-- Mobile: stacked card list -->
      <ul class="flex flex-col gap-2 md:hidden" aria-label={m.flow_history()}>
        {#each renderedRuns as run (run.id)}
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
                  {getRunVersionLabel(run)}
                </Badge>
              </div>
              <div class="flex items-center justify-between gap-2">
                <p class="text-secondary truncate text-sm tabular-nums">
                  {new Date(run.created_at).toLocaleString(getLocale())}
                </p>
                <div class="flex shrink-0 items-center gap-1.5">
                  {#if showAdvancedControls}
                    <FlowRunTokenUsageBadge tokenUsage={run.token_usage} interactive={false} />
                    <FlowRunTranscriptionUsageBadge transcriptionUsage={run.transcription_usage} />
                  {/if}
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
                    onclick={() => void redispatchRun(run)}
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
            {#if isExpanded && mobileViewport.current}
              <div
                id={getEvidenceRowId(run.id)}
                class="border-default bg-muted/30 border-t px-3 py-3"
              >
                {@render stepRunDetail(run)}
              </div>
            {/if}
          </li>
        {/each}
      </ul>

      <footer class="text-muted flex flex-wrap items-center justify-between gap-3 text-xs">
        <span role="status">
          {#if hasHiddenMatches}
            {m.flow_history_showing_count_of({
              shown: String(renderedRuns.length),
              count: String(visibleRuns.length)
            })}
          {:else}
            {visibleRuns.length === 1
              ? m.flow_history_showing_count_one()
              : m.flow_history_showing_count({ count: String(visibleRuns.length) })}
          {/if}
        </span>
        <span class="flex items-center gap-2">
          {#if history.loadMoreError}
            <span class="text-negative-default" role="alert">
              {m.flow_history_load_more_failed()}
            </span>
          {/if}
          {#if hasHiddenMatches || canLoadMore}
            <Button
              variant="outline"
              size="sm"
              disabled={!hasHiddenMatches && history.inFlightGeneration !== null}
              onclick={() => {
                if (hasHiddenMatches) {
                  renderLimit += RENDERED_RUNS_PAGE_SIZE;
                } else {
                  // Reveal the fetched rows in the same action — the fetch
                  // must not require a second click to become visible.
                  renderLimit += RENDERED_RUNS_PAGE_SIZE;
                  void loadMoreRuns();
                }
              }}
            >
              {history.loadMoreError && !hasHiddenMatches
                ? m.flow_retry()
                : m.flow_history_load_more()}
            </Button>
          {:else if history.hasMore && windowFull}
            <span
              >{m.flow_history_window_full({
                count: MAX_LOADED_FLOW_RUNS.toLocaleString(getLocale())
              })}</span
            >
          {/if}
        </span>
      </footer>
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
