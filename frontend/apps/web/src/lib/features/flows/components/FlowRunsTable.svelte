<script lang="ts">
  import {
    EneoError,
    type Eneo,
    type Flow,
    type FlowRun,
    type FlowRunSummary
  } from "@eneo/eneo-js";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as ToggleGroup from "$lib/components/ui/toggle-group/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import FlowRunEvidence from "./FlowRunEvidence.svelte";
  import FlowRunProgressPanel from "./FlowRunProgressPanel.svelte";
  import type { FlowRunFailureRepairTarget } from "$lib/features/flows/flowRunFailureRepair";
  import FlowRunReviewCheckpointPanel from "./FlowRunReviewCheckpointPanel.svelte";
  import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";
  import { getLocale } from "$lib/paraglide/runtime";
  import { toast } from "$lib/components/toast";
  import { getFlowRunStatusLabel } from "./flowRunStatusLabel";
  import { getRedispatchToastKind } from "./flowRunRedispatchFeedback";
  import { m } from "$lib/paraglide/messages";
  import { formatFlowRunDuration, type FlowRunProgressSnapshot } from "./flowRunProgress";
  import { getConfirmedOptimisticFlowRunIds, mergeOptimisticFlowRuns } from "./flowRunsOptimistic";
  import {
    canRedispatchFlowRun,
    FLOW_RUN_STATUS_FILTER_OPTIONS,
    isFlowRunActive,
    isFlowRunAwaitingReview,
    isFlowRunCancellable,
    shouldPollFlowRunStatus,
    type FlowRunStatusFilter
  } from "./flowRunStatusSets";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { IsMobile } from "$lib/hooks/is-mobile.svelte";
  import type { FlowCareDataPolicy } from "$lib/features/flows/flowCareDataPolicy";
  import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";
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
    onOptimisticRunsConfirmed,
    onreview,
    onrepair
  }: {
    flow: Flow;
    careDataPolicy?: FlowCareDataPolicy;
    eneo: Eneo;
    visible?: boolean;
    optimisticRuns?: FlowRun[];
    reloadTrigger?: number;
    onOptimisticRunsConfirmed?: (runIds: string[]) => void;
    /** Offered when the AI builder can review these runs; opens it. */
    onreview?: () => void;
    /** Offered when the AI builder can repair a failed step; opens it on that step. */
    onrepair?: (target: FlowRunFailureRepairTarget) => void;
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
  const historyTableColumnCount = 5;
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

  function getRunVersionLabel(run: FlowRunSummary): string {
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

  function toggleSort(key: FlowRunHistorySortKey) {
    sortState = nextFlowRunHistorySortState(sortState, key);
  }

  function ariaSortFor(key: FlowRunHistorySortKey): "ascending" | "descending" | "none" {
    return getFlowRunHistoryAriaSort(sortState, key);
  }
  let redispatchingRunId: string | null = $state(null);
  let cancellingRunId: string | null = $state(null);
  let retryingRunId: string | null = $state(null);
  let showCancelConfirm = $state(false);
  let pendingCancelRunId: string | null = $state(null);
  let progressSnapshotsByRunId = $state<Record<string, FlowRunProgressSnapshot>>({});
  // Counts completed run-list reads; the expanded progress panel re-reads
  // step statuses on each one so it moves with the row.
  let runListRefreshTick = $state(0);
  const runStartedFormat = $derived(
    new Intl.DateTimeFormat(getLocale(), { dateStyle: "short", timeStyle: "short" })
  );
  // Clock for runs that have not finished. It moves with the poll, so an
  // elapsed time is never older than one refresh.
  let nowMs = $state(Date.now());

  async function loadRuns(mode: "refresh" | "more" = "refresh") {
    const result = await loadFlowRunHistory(history, {
      flowId: flow?.id,
      mode,
      listRuns: async (flowId, page) =>
        eneo.flows.runs.list({ flowId, limit: page.limit, offset: page.offset }),
      pollableRefresh: {
        getStatus: async (flowId, runId) => eneo.flows.runs.status({ id: runId, flowId }),
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
      runListRefreshTick += 1;
      nowMs = Date.now();
      const nextRuns = result.runs;
      const confirmedOptimisticRunIds = getConfirmedOptimisticFlowRunIds(nextRuns, optimisticRuns);
      if (confirmedOptimisticRunIds.length > 0) {
        onOptimisticRunsConfirmed?.(confirmedOptimisticRunIds);
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
    return formatFlowRunDuration(new Date(end).getTime() - new Date(start).getTime());
  }

  // A run still going has no end time, and with several going at once how long
  // each has been waiting is the fact the reviewer is after.
  function formatElapsed(start: string): string {
    return formatFlowRunDuration(nowMs - new Date(start).getTime());
  }

  function isRunInFlight(status: FlowRunSummary["status"]): boolean {
    return isFlowRunActive(status) || isFlowRunAwaitingReview(status);
  }

  async function redispatchRun(run: FlowRunSummary) {
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

  // The server chooses the first unfinished step and reuses the completed
  // prefix; the key is stable per source revision, so a double click returns
  // the same child run instead of a second one.
  async function retryRun(run: FlowRunSummary) {
    // One request slot: every retry action is disabled while it is taken,
    // so a second click cannot re-enable or clear another row's pending state.
    if (retryingRunId !== null) return;
    retryingRunId = run.id;
    try {
      const result = await eneo.flows.runs.retryFromFailedStep({
        flowId: flow.id,
        runId: run.id,
        idempotencyKey: `flow-run-retry:${run.id}:${run.revision}`
      });
      if (result.created) {
        toast.success(m.flow_run_retry_started({ step: String(result.first_executed_step_order) }));
      } else {
        // The same key returned the child created earlier; nothing was
        // dispatched now, and that child may already have finished.
        toast.info(m.flow_run_retry_replayed());
      }
      await loadRuns();
    } catch (error) {
      console.error("Failed to retry run", error);
      toast.error(getFlowRuntimeErrorMessage(error, m.flow_run_retry_failed()));
    } finally {
      retryingRunId = null;
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
</script>

{#snippet stepRunDetail(run: FlowRunSummary)}
  {#if isFlowRunActive(run.status)}
    <FlowRunProgressPanel
      runId={run.id}
      flowId={flow.id}
      {eneo}
      runStartedAt={run.started_at ?? run.created_at}
      initialSnapshot={progressSnapshotsByRunId[run.id] ?? null}
      refreshTick={runListRefreshTick}
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
      onRepairFailure={onrepair ?? null}
    />
  {/if}
{/snippet}

<section class="mx-auto flex w-full max-w-[1400px] flex-col gap-4 px-3 py-4 sm:px-6 sm:py-6">
  <header class="flex flex-wrap items-center justify-between gap-3">
    <div class="min-w-0">
      <!-- The selected tab already says "Historik" a few pixels above, so the
           heading is kept for heading navigation and not repeated on screen.
           The Builder panel opens the same way, with its summary line first. -->
      <h2 class="sr-only">{m.flow_history()}</h2>
      <!-- The mode explainer describes what the list shows; with no runs there
           is nothing to explain and the empty state carries the next step. -->
      {#if displayRuns.length > 0}
        <p class="text-secondary max-w-2xl text-sm leading-relaxed">
          {historyModeDescription}
        </p>
      {/if}
    </div>
    {#if onreview}
      <Button variant="outline" size="sm" class="h-9" onclick={() => onreview?.()}>
        {m.flow_history_review_with_builder()}
      </Button>
    {/if}
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
      class="border-default bg-primary rounded-xl border px-6 py-14 text-center"
      aria-label={m.flow_no_runs_yet()}
    >
      <p class="text-primary text-sm font-semibold">{m.flow_no_runs_yet()}</p>
      <!-- A draft cannot be run, so the honest next step differs. -->
      <p class="text-secondary mx-auto mt-1 max-w-[42ch] text-sm leading-relaxed text-pretty">
        {flow.published_version != null
          ? m.flow_no_runs_yet_published()
          : m.flow_no_runs_yet_draft()}
      </p>
    </div>
  {:else}
    {#if history.refreshWarning}
      <Alert.Root>
        <Alert.Title>{m.flow_history_refresh_failed_title()}</Alert.Title>
        <Alert.Description>{m.flow_history_refresh_failed_desc()}</Alert.Description>
        <Alert.Action>
          <Button
            variant="outline"
            size="sm"
            disabled={history.inFlightGeneration !== null}
            onclick={() => void loadRuns()}
          >
            {m.flow_retry()}
          </Button>
        </Alert.Action>
      </Alert.Root>
    {/if}
    <!-- The field sits on the linen page, where a transparent surface reads as
         inert and drops the placeholder below the contrast floor. -->
    <div class="mb-3 flex flex-wrap items-start gap-x-3 gap-y-2">
      <div class="relative w-full max-w-md min-w-60 flex-1">
        <Input
          type="search"
          bind:value={searchQuery}
          placeholder={m.flow_history_search_placeholder()}
          aria-label={m.flow_history_search_placeholder()}
          aria-describedby={searchQuery ? searchScopeHintId : undefined}
          class="bg-primary h-9"
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
      <!-- One single-choice control with one keyboard model, as on the flows
         list: arrow keys move between statuses, the chosen one stays set. -->
      <ToggleGroup.Root
        type="single"
        variant="outline"
        spacing={0}
        class="flex-wrap"
        value={statusFilter ?? "all"}
        onValueChange={(value) => {
          if (value) statusFilter = value === "all" ? null : (value as FlowRunStatusFilter);
        }}
        aria-label={m.filter()}
      >
        <ToggleGroup.Item value="all" class="gap-1.5 px-3">
          {m.all_categories()}
          <span class="text-secondary font-normal tabular-nums">{displayRuns.length}</span>
        </ToggleGroup.Item>
        {#each FLOW_RUN_STATUS_FILTER_OPTIONS as status (status)}
          {@const count = statusCounts[status] ?? 0}
          {#if count > 0}
            <ToggleGroup.Item value={status} class="gap-1.5 px-3">
              {getRunStatusLabel(status)}
              <span class="text-secondary font-normal tabular-nums">{count}</span>
            </ToggleGroup.Item>
          {/if}
        {/each}
      </ToggleGroup.Root>
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
            <span class="text-negative-stronger text-xs" role="alert">
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
                class="text-muted h-11 px-0 text-xs font-medium"
              >
                {#if showAdvancedControls}
                  <Button
                    type="button"
                    variant="ghost"
                    class="text-muted hover:text-primary focus-visible:ring-ring h-11 w-full justify-start gap-1 rounded-none px-4 text-xs font-medium focus-visible:ring-inset"
                    onclick={() => toggleSort("status")}
                  >
                    {m.status()}
                    {#if sortState.key === "status"}
                      <IconChevronDown
                        class="size-3 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {sortState.dir ===
                        'asc'
                          ? 'rotate-180'
                          : ''}"
                        aria-hidden="true"
                      />
                    {/if}
                  </Button>
                {:else}
                  <span class="block px-4">{m.status()}</span>
                {/if}
              </Table.Head>
              <Table.Head class="text-muted hidden h-11 px-4 text-xs font-medium lg:table-cell">
                {m.version()}
              </Table.Head>
              <Table.Head
                aria-sort={showAdvancedControls ? ariaSortFor("started") : undefined}
                class="text-muted h-11 px-0 text-xs font-medium"
              >
                {#if showAdvancedControls}
                  <Button
                    type="button"
                    variant="ghost"
                    class="text-muted hover:text-primary focus-visible:ring-ring h-11 w-full justify-start gap-1 rounded-none px-4 text-xs font-medium focus-visible:ring-inset"
                    onclick={() => toggleSort("started")}
                  >
                    {m.flow_run_started()}
                    {#if sortState.key === "started"}
                      <IconChevronDown
                        class="size-3 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {sortState.dir ===
                        'asc'
                          ? 'rotate-180'
                          : ''}"
                        aria-hidden="true"
                      />
                    {/if}
                  </Button>
                {:else}
                  <span class="block px-4">{m.flow_run_started()}</span>
                {/if}
              </Table.Head>
              <Table.Head
                aria-sort={showAdvancedControls ? ariaSortFor("duration") : undefined}
                class="text-muted hidden h-11 px-0 text-xs font-medium lg:table-cell"
              >
                {#if showAdvancedControls}
                  <Button
                    type="button"
                    variant="ghost"
                    class="text-muted hover:text-primary focus-visible:ring-ring h-11 w-full justify-start gap-1 rounded-none px-4 text-xs font-medium focus-visible:ring-inset"
                    onclick={() => toggleSort("duration")}
                  >
                    {m.duration()}
                    {#if sortState.key === "duration"}
                      <IconChevronDown
                        class="size-3 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {sortState.dir ===
                        'asc'
                          ? 'rotate-180'
                          : ''}"
                        aria-hidden="true"
                      />
                    {/if}
                  </Button>
                {:else}
                  <span class="block px-4">{m.duration()}</span>
                {/if}
              </Table.Head>
              <Table.Head class="text-muted h-11 px-4 text-right text-xs font-medium">
                <span class="sr-only">{m.actions()}</span>
              </Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each renderedRuns as run (run.id)}
              {@const isExpanded = selectedRunId === run.id}
              <Table.Row
                class="border-default hover:bg-muted/40 focus-visible:inset-ring-ring cursor-pointer focus-visible:inset-ring-2 focus-visible:outline-none motion-safe:transition-colors motion-safe:duration-(--duration-micro) {isExpanded
                  ? 'bg-muted/50'
                  : ''}"
                tabindex={0}
                onclick={() => toggleRunDetails(run.id)}
                onkeydown={(e) => {
                  // Buttons inside the row (retry, re-run, cancel) own their
                  // own Enter and Space; the row reacts only when it is the
                  // focused element itself.
                  if (e.target !== e.currentTarget) return;
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
                  {runStartedFormat.format(new Date(run.created_at))}
                </Table.Cell>
                <Table.Cell
                  class="text-secondary hidden px-4 py-3 align-middle tabular-nums lg:table-cell"
                >
                  {#if run.status === "completed" || run.status === "failed"}
                    {formatDuration(run.created_at, run.updated_at)}
                  {:else if isRunInFlight(run.status)}
                    {formatElapsed(run.created_at)}
                  {:else}
                    <span aria-hidden="true">—</span>
                  {/if}
                </Table.Cell>
                <!-- eslint-disable-next-line a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                <Table.Cell
                  class="px-2 py-2 text-right align-middle"
                  onclick={(e: MouseEvent) => e.stopPropagation()}
                >
                  <!-- Cells keep their text on one line; the action group wraps
                       instead so a narrow viewport never scrolls the table sideways. -->
                  <div class="flex flex-wrap items-center justify-end gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      data-testid={`flow-run-evidence-toggle-${run.id}`}
                      aria-expanded={isExpanded}
                      aria-controls={isExpanded ? getEvidenceRowId(run.id) : undefined}
                      onclick={() => toggleRunDetails(run.id)}
                    >
                      {isExpanded ? m.flow_run_hide_details() : m.flow_run_show_details()}
                      <IconChevronDown
                        data-icon="inline-end"
                        class="motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {isExpanded
                          ? 'rotate-180'
                          : ''}"
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
                    {#if run.status === "failed"}
                      <Button
                        variant="outline"
                        size="sm"
                        data-testid={`flow-run-retry-${run.id}`}
                        disabled={retryingRunId !== null}
                        onclick={() => void retryRun(run)}
                      >
                        {retryingRunId === run.id ? m.flow_run_retrying() : m.flow_run_retry()}
                      </Button>
                    {/if}
                    {#if isFlowRunCancellable(run.status)}
                      <Button
                        variant="ghost"
                        size="sm"
                        class="text-negative-stronger hover:bg-negative-dimmer/50 hover:text-negative-stronger"
                        disabled={cancellingRunId === run.id}
                        onclick={() => requestCancelRun(run.id)}
                      >
                        {cancellingRunId === run.id ? m.flow_run_cancelling() : m.cancel()}
                      </Button>
                    {/if}
                  </div>
                </Table.Cell>
              </Table.Row>
              {#if isExpanded && !mobileViewport.current}
                <Table.Row class="border-default hover:bg-transparent">
                  <!-- `max-w-0` keeps this cell out of the column algorithm.
                       The table is auto-layout, which sizes columns from the
                       max-content width of their cells, and this one holds a
                       `white-space: pre` prompt and megabytes of JSON. The
                       inner `overflow-auto` stops those blocks scrolling the
                       page but does not stop the table measuring what is
                       behind them, so the table grew to 3113px inside its
                       1353px scroll wrapper: a horizontal scrollbar onto
                       blank space. Constrained, the cell still fills the row
                       and the real columns keep their own proportions. -->
                  <Table.Cell
                    id={getEvidenceRowId(run.id)}
                    colspan={historyTableColumnCount}
                    class="bg-muted/30 max-w-0 px-3 py-4"
                  >
                    <div class="t-evidence-reveal">
                      {@render stepRunDetail(run)}
                    </div>
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
              data-testid={`flow-run-evidence-toggle-mobile-${run.id}`}
              class="focus-visible:ring-ring flex w-full flex-col gap-2 rounded-xl px-4 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-inset"
              aria-expanded={isExpanded}
              aria-controls={isExpanded ? getEvidenceRowId(run.id) : undefined}
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
                  {runStartedFormat.format(new Date(run.created_at))}
                </p>
                <div class="flex shrink-0 items-center gap-1.5">
                  {#if run.status === "completed" || run.status === "failed"}
                    <p class="text-muted text-xs tabular-nums">
                      {formatDuration(run.created_at, run.updated_at)}
                    </p>
                  {:else if isRunInFlight(run.status)}
                    <p class="text-muted text-xs tabular-nums">
                      {formatElapsed(run.created_at)}
                    </p>
                  {/if}
                </div>
              </div>
            </button>
            {#if run.status === "failed"}
              <div class="border-default flex items-center gap-2 border-t px-4 py-2">
                <Button
                  variant="outline"
                  size="sm"
                  class="flex-1"
                  data-testid={`flow-run-retry-mobile-${run.id}`}
                  disabled={retryingRunId !== null}
                  onclick={() => void retryRun(run)}
                >
                  {retryingRunId === run.id ? m.flow_run_retrying() : m.flow_run_retry()}
                </Button>
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
                  variant="ghost"
                  size="sm"
                  class="text-negative-stronger hover:bg-negative-dimmer/50 hover:text-negative-stronger flex-1"
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
            <span class="text-negative-stronger" role="alert">
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

<style lang="postcss">
  /* transitions-dev: a short rise so the evidence reads as opening out of its
     row rather than appearing from nowhere. Tokens live in app.css; the global
     reduced-motion guard in app.css neutralises the duration, and the rule below
     removes the offset so nothing starts displaced. */
  .t-evidence-reveal {
    animation: evidence-reveal var(--duration-fast) var(--ease-smooth-out) both;
  }
  @keyframes evidence-reveal {
    from {
      opacity: 0;
      transform: translateY(calc(var(--distance-base) * -1));
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .t-evidence-reveal {
      animation: none;
    }
  }
</style>
