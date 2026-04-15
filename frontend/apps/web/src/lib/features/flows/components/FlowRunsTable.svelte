<script lang="ts">
  import type { Flow, FlowRun, Intric } from "@intric/intric-js";
  import { untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconArrowDownToLine } from "@intric/icons/arrow-down-to-line";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import FlowRunEvidence from "./FlowRunEvidence.svelte";
  import FlowRunProgressPanel from "./FlowRunProgressPanel.svelte";
  import { toast } from "$lib/components/toast";
  import { getRedispatchToastKind } from "./flowRunRedispatchFeedback";
  import { m } from "$lib/paraglide/messages";
  import { isFlowRunActive, type FlowRunProgressSnapshot } from "./flowRunProgress";
  import {
    getFlowRunLocalizedStatusLabel,
    getFlowRunStatusColor,
    getFlowRunStatusDotColor
  } from "./flowRunStatusPresentation";
  import { shouldHandleFlowRunsReload } from "./flowRunsReload";

  let {
    flow,
    eneo,
    visible = true,
    reloadTrigger = 0,
    latestRunPayload = $bindable(null),
    pendingHighlightRunId = $bindable(null)
  }: {
    flow: Flow;
    eneo: Intric;
    visible?: boolean;
    reloadTrigger?: number;
    latestRunPayload?: Record<string, unknown> | null;
    pendingHighlightRunId?: string | null;
  } = $props();

  let runs: FlowRun[] = $state([]);
  let loading = $state(true);
  let loadError: string | null = $state(null);
  let selectedRunId: string | null = $state(null);
  let lastLoadedFlowId: string | null = $state(null);
  let isInitialLoad = $state(true);
  let lastHandledReloadTrigger = $state(0);
  let redispatchingRunId: string | null = $state(null);
  let cancellingRunId: string | null = $state(null);
  let showCancelConfirm = $state(false);
  let pendingCancelRunId: string | null = $state(null);
  let progressSnapshotsByRunId = $state<Record<string, FlowRunProgressSnapshot>>({});
  let isRunListPolling = $state(false);

  async function loadRuns() {
    if (isRunListPolling) return;
    isRunListPolling = true;
    if (!flow?.id) {
      runs = [];
      loading = false;
      isRunListPolling = false;
      return;
    }
    if (isInitialLoad) loading = true;
    loadError = null;
    try {
      const result = await eneo.flows.runs.list({ flowId: flow.id });
      runs = (result.items ?? result) as FlowRun[];
      latestRunPayload = runs.length > 0 ? (runs[0].input_payload_json ?? null) : null;
      if (pendingHighlightRunId && runs.some((r) => r.id === pendingHighlightRunId)) {
        selectedRunId = pendingHighlightRunId;
        pendingHighlightRunId = null;
      }
      isInitialLoad = false;
    } catch (e) {
      console.error("Error loading flow runs", e);
      loadError = e instanceof Error ? e.message : "Failed to load runs";
    } finally {
      loading = false;
      isRunListPolling = false;
    }
  }

  $effect(() => {
    if (flow?.id && flow.id !== lastLoadedFlowId) {
      lastLoadedFlowId = flow.id;
      void loadRuns();
    } else if (!flow?.id) {
      lastLoadedFlowId = null;
      loading = false;
    }
  });

  $effect(() => {
    if (shouldHandleFlowRunsReload(reloadTrigger, lastHandledReloadTrigger)) {
      lastHandledReloadTrigger = reloadTrigger;
      untrack(() => {
        void loadRuns();
      });
    }
  });

  // Poll for updates every 5s when there are running runs
  let pollTimeout: ReturnType<typeof setTimeout> | null = null;
  let hasActiveRuns = $derived(runs.some((r) => r.status === "queued" || r.status === "running"));

  $effect(() => {
    if (hasActiveRuns && !pollTimeout && visible) {
      const scheduleNextPoll = () => {
        pollTimeout = setTimeout(async () => {
          await loadRuns();
          pollTimeout = null;
          if (hasActiveRuns && visible) {
            scheduleNextPoll();
          }
        }, 5000);
      };
      scheduleNextPoll();
    } else if ((!hasActiveRuns || !visible) && pollTimeout) {
      clearTimeout(pollTimeout);
      pollTimeout = null;
    }
  });

  $effect(() => {
    return () => {
      if (pollTimeout) clearTimeout(pollTimeout);
    };
  });

  function getStatusColor(status: string): string {
    return getFlowRunStatusColor(status);
  }

  function getStatusDotColor(status: string): string {
    return getFlowRunStatusDotColor(status);
  }

  function getStatusLabel(status: string): string {
    return getFlowRunLocalizedStatusLabel(status, {
      completed: m.flow_run_status_completed,
      failed: m.flow_run_status_failed,
      queued: m.flow_run_status_queued,
      running: m.flow_run_status_running,
      cancelled: m.flow_run_status_cancelled
    });
  }

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
</script>

<section class="mx-auto flex w-full max-w-[1400px] flex-col gap-4 px-3 py-4 sm:px-6 sm:py-6">
  <header class="flex items-center justify-between gap-3">
    <h2 class="text-primary text-base font-semibold tracking-tight sm:text-lg">
      {m.flow_history()}
    </h2>
    {#if runs.length > 0}
      <p class="text-muted text-xs tabular-nums">
        {runs.length}
      </p>
    {/if}
  </header>

  {#if loading}
    <div class="text-muted flex items-center justify-center gap-2 py-10 text-sm">
      <IconLoadingSpinner class="size-4 animate-spin" />
      {m.flow_loading()}
    </div>
  {:else if loadError}
    <Alert.Root variant="destructive">
      <Alert.Description>{loadError}</Alert.Description>
      <Alert.Action>
        <Button variant="outline" size="sm" onclick={loadRuns}>
          {m.flow_retry()}
        </Button>
      </Alert.Action>
    </Alert.Root>
  {:else if runs.length === 0}
    <div
      class="border-default bg-primary rounded-xl border py-14 text-center"
      aria-label={m.flow_no_runs_yet()}
    >
      <p class="text-muted text-sm">{m.flow_no_runs_yet()}</p>
    </div>
  {:else}
    <!-- Desktop: Table -->
    <div
      class="border-default bg-primary hidden overflow-hidden rounded-xl border shadow-xs md:block"
    >
      <Table.Root>
        <Table.Header>
          <Table.Row class="border-default hover:bg-transparent">
            <Table.Head class="text-muted h-11 px-4 text-xs font-medium tracking-wide uppercase">
              {m.status()}
            </Table.Head>
            <Table.Head
              class="text-muted hidden h-11 px-4 text-xs font-medium tracking-wide uppercase lg:table-cell"
            >
              {m.version()}
            </Table.Head>
            <Table.Head class="text-muted h-11 px-4 text-xs font-medium tracking-wide uppercase">
              {m.flow_run_started()}
            </Table.Head>
            <Table.Head
              class="text-muted hidden h-11 px-4 text-xs font-medium tracking-wide uppercase lg:table-cell"
            >
              {m.duration()}
            </Table.Head>
            <Table.Head
              class="text-muted h-11 px-4 text-right text-xs font-medium tracking-wide uppercase"
            >
              <span class="sr-only">{m.actions()}</span>
            </Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each runs as run (run.id)}
            {@const isExpanded = selectedRunId === run.id}
            <Table.Row
              class="border-default hover:bg-muted/40 cursor-pointer transition-colors {isExpanded
                ? 'bg-muted/50'
                : ''}"
              tabindex="0"
              onclick={() => toggleRunDetails(run.id)}
              onkeydown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggleRunDetails(run.id);
                }
              }}
            >
              <Table.Cell class="px-4 py-3 align-middle">
                <span
                  class="{getStatusColor(
                    run.status
                  )} inline-flex items-center gap-2 text-xs font-medium"
                >
                  <span
                    class="{getStatusDotColor(run.status)} size-1.5 shrink-0 rounded-full"
                    aria-hidden="true"
                  ></span>
                  {getStatusLabel(run.status)}
                </span>
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
                {:else}
                  —
                {/if}
              </Table.Cell>
              <!-- eslint-disable-next-line a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
              <Table.Cell
                class="px-2 py-2 text-right align-middle"
                onclick={(e: MouseEvent) => e.stopPropagation()}
              >
                <div class="inline-flex items-center gap-1">
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
                  {#if run.status === "queued"}
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
                  {#if run.status === "queued" || run.status === "running"}
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
            {#if run.status === "failed" && run.error_message}
              <Table.Row class="border-default hover:bg-transparent">
                <Table.Cell colspan={5} class="px-4 py-2">
                  <Alert.Root variant="destructive">
                    <Alert.Title class="text-xs font-semibold">{m.flow_run_error()}</Alert.Title>
                    <Alert.Description class="text-xs break-words">
                      {run.error_message}
                    </Alert.Description>
                  </Alert.Root>
                </Table.Cell>
              </Table.Row>
            {/if}
            {#if run.status === "completed" && run.output_payload_json}
              <Table.Row class="border-default hover:bg-transparent">
                <Table.Cell colspan={5} class="px-4 py-2">
                  <div
                    class="bg-positive-dimmer/25 border-positive-default/20 flex flex-col gap-1.5 rounded-lg border px-3 py-2.5 text-xs"
                  >
                    {#if run.output_payload_json.structured}
                      {@const structured = run.output_payload_json.structured}
                      {#if Array.isArray(structured)}
                        <div class="text-secondary flex flex-wrap items-baseline gap-x-3 gap-y-1">
                          <span class="text-positive-stronger font-semibold">
                            {m.flow_run_output()}:
                          </span>
                          {#each structured.slice(0, 3) as item, i (i)}
                            <span class="font-mono">
                              #{i + 1}: {JSON.stringify(item).slice(0, 80)}{JSON.stringify(item)
                                .length > 80
                                ? "\u2026"
                                : ""}
                            </span>
                          {/each}
                          {#if structured.length > 3}
                            <span class="text-muted">+{structured.length - 3} more</span>
                          {/if}
                        </div>
                      {:else}
                        {@const entries = Object.entries(structured).slice(0, 4)}
                        <div class="text-secondary flex flex-wrap items-baseline gap-x-4 gap-y-1">
                          <span class="text-positive-stronger font-semibold">
                            {m.flow_run_output()}:
                          </span>
                          {#each entries as [key, val] (key)}
                            <span>
                              <span class="text-positive-stronger font-semibold">{key}:</span>
                              <span class="text-secondary">
                                {String(val).slice(0, 80)}{String(val).length > 80 ? "\u2026" : ""}
                              </span>
                            </span>
                          {/each}
                          {#if Object.keys(structured).length > 4}
                            <span class="text-muted">
                              +{Object.keys(structured).length - 4} more
                            </span>
                          {/if}
                        </div>
                      {/if}
                    {:else if run.output_payload_json.text && !run.output_payload_json.artifacts?.length}
                      <div class="text-secondary truncate">
                        <span class="text-positive-stronger font-semibold">
                          {m.flow_run_output()}:
                        </span>
                        {String(run.output_payload_json.text).slice(0, 200)}{String(
                          run.output_payload_json.text
                        ).length > 200
                          ? "\u2026"
                          : ""}
                      </div>
                    {/if}
                    {#if run.output_payload_json.artifacts?.length}
                      <div class="flex flex-wrap items-center gap-2">
                        {#each run.output_payload_json.artifacts as artifact (artifact.file_id)}
                          <button
                            type="button"
                            class="border-default bg-primary hover:border-dimmer hover:bg-hover-default text-secondary inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors"
                            onclick={() => downloadArtifact(run.id, artifact.file_id)}
                          >
                            <IconArrowDownToLine class="size-3" />
                            {artifact.name}
                          </button>
                        {/each}
                      </div>
                    {/if}
                  </div>
                </Table.Cell>
              </Table.Row>
            {/if}
            {#if isExpanded}
              <Table.Row class="border-default hover:bg-transparent">
                <Table.Cell id={getEvidenceRowId(run.id)} colspan={5} class="bg-muted/30 px-3 py-4">
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
                  {:else}
                    <FlowRunEvidence
                      runId={run.id}
                      flowId={flow.id}
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
      {#each runs as run (run.id)}
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
              <span
                class="{getStatusColor(
                  run.status
                )} inline-flex items-center gap-2 text-xs font-medium"
              >
                <span
                  class="{getStatusDotColor(run.status)} size-1.5 shrink-0 rounded-full"
                  aria-hidden="true"
                ></span>
                {getStatusLabel(run.status)}
              </span>
              <Badge variant="outline" class="h-5 shrink-0 text-xs font-medium tabular-nums">
                v{run.flow_version}
              </Badge>
            </div>
            <div class="flex items-center justify-between gap-2">
              <p class="text-secondary truncate text-sm tabular-nums">
                {new Date(run.created_at).toLocaleString()}
              </p>
              {#if run.status === "completed" || run.status === "failed"}
                <p class="text-muted shrink-0 text-xs tabular-nums">
                  {formatDuration(run.created_at, run.updated_at)}
                </p>
              {/if}
            </div>
          </button>
          {#if run.status === "queued" || run.status === "running"}
            <div class="border-default flex items-center gap-2 border-t px-4 py-2">
              {#if run.status === "queued"}
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
</section>

<AlertDialog.Root bind:open={showCancelConfirm}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.cancel()}</AlertDialog.Title>
      <AlertDialog.Description>{m.flow_run_cancel_confirm()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={confirmCancelRun}>
        {m.cancel()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
