<script lang="ts">
  import type { Flow, FlowRun, Intric } from "@intric/intric-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconArrowDownToLine } from "@intric/icons/arrow-down-to-line";
  import * as Alert from "$lib/components/ui/alert/index.js";
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
    if (reloadTrigger) {
      void loadRuns();
    }
  });

  // Poll for updates every 5s when there are running runs
  let pollTimeout: ReturnType<typeof setTimeout> | null = $state(null);
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

  function updateProgressSnapshot(runId: string, snapshot: FlowRunProgressSnapshot) {
    progressSnapshotsByRunId = {
      ...progressSnapshotsByRunId,
      [runId]: snapshot
    };
  }
</script>

<div class="mx-auto flex w-full max-w-[1400px] flex-col gap-4 p-4 md:p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-lg font-semibold">{m.flow_history()}</h2>
    <div class="flex items-center gap-2"></div>
  </div>

  {#if loading}
    <div class="text-secondary flex items-center justify-center gap-2 py-8 text-sm">
      <IconLoadingSpinner class="size-4 animate-spin" />
      {m.flow_loading()}
    </div>
  {:else if loadError}
    <Alert.Root variant="destructive" class="flex items-center gap-3 px-5 py-4">
      <Alert.Description class="flex-1 text-sm">{loadError}</Alert.Description>
      <Alert.Action>
        <Button variant="outline" size="sm" onclick={loadRuns} class="gap-1.5 text-xs">
          {m.flow_retry()}
        </Button>
      </Alert.Action>
    </Alert.Root>
  {:else if runs.length === 0}
    <p class="text-secondary py-8 text-center text-sm">{m.flow_no_runs_yet()}</p>
  {:else}
    <div class="border-default overflow-hidden rounded-lg border">
      <div class="overflow-x-auto">
        <table class="w-full text-sm" aria-label={m.flow_history()}>
          <thead>
            <tr class="border-default border-b text-left">
              <th scope="col" class="text-muted px-3 py-2.5 text-xs font-medium sm:px-4"
                >{m.status()}</th
              >
              <th
                scope="col"
                class="text-muted hidden px-4 py-2.5 text-xs font-medium sm:table-cell"
                >{m.version()}</th
              >
              <th scope="col" class="text-muted px-3 py-2.5 text-xs font-medium sm:px-4"
                >{m.flow_run_started()}</th
              >
              <th
                scope="col"
                class="text-muted hidden px-4 py-2.5 text-xs font-medium md:table-cell"
                >{m.duration()}</th
              >
              <th scope="col" class="text-muted px-3 py-2.5 text-xs font-medium sm:px-4"
                >{m.actions()}</th
              >
            </tr>
          </thead>
          <tbody>
            {#each runs as run (run.id)}
              <tr
                class={[
                  "border-dimmer hover:bg-hover-dimmer cursor-pointer border-b transition-colors last:border-b-0",
                  selectedRunId === run.id && "bg-accent-dimmer/30"
                ]}
                tabindex="0"
                onclick={() => (selectedRunId = selectedRunId === run.id ? null : run.id)}
                onkeydown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    selectedRunId = selectedRunId === run.id ? null : run.id;
                  }
                }}
              >
                <td class="px-3 py-3 sm:px-4">
                  <span
                    class="{getStatusColor(
                      run.status
                    )} inline-flex items-center gap-1.5 text-xs font-medium"
                  >
                    <span class="{getStatusDotColor(run.status)} size-1.5 shrink-0 rounded-full"
                    ></span>
                    {getStatusLabel(run.status)}
                  </span>
                </td>
                <td class="text-secondary hidden px-4 py-3 tabular-nums sm:table-cell"
                  >v{run.flow_version}</td
                >
                <td class="text-secondary px-3 py-3 sm:px-4">
                  {new Date(run.created_at).toLocaleString()}
                </td>
                <td class="text-secondary hidden px-4 py-3 tabular-nums md:table-cell">
                  {#if run.status === "completed" || run.status === "failed"}
                    {formatDuration(run.created_at, run.updated_at)}
                  {:else if run.status === "running"}
                    <span class="text-accent-stronger">{m.flow_run_running()}</span>
                  {:else}
                    -
                  {/if}
                </td>
                <td class="px-3 py-2 sm:px-4" onclick={(e) => e.stopPropagation()}>
                  <div class="flex items-center gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      aria-expanded={selectedRunId === run.id}
                      aria-controls={getEvidenceRowId(run.id)}
                      onclick={() => (selectedRunId = selectedRunId === run.id ? null : run.id)}
                    >
                      {m.flow_run_evidence()}
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
                </td>
              </tr>
              {#if run.status === "failed" && run.error_message}
                <tr>
                  <td colspan="5" class="border-default border-b px-4 py-2">
                    <Alert.Root
                      variant="destructive"
                      class="flex min-w-0 items-start gap-2 text-xs"
                    >
                      <Alert.Title class="shrink-0 text-xs font-semibold"
                        >{m.flow_run_error()}:</Alert.Title
                      >
                      <Alert.Description class="min-w-0 text-xs break-words"
                        >{run.error_message}</Alert.Description
                      >
                    </Alert.Root>
                  </td>
                </tr>
              {/if}
              {#if run.status === "completed" && run.output_payload_json}
                <tr>
                  <td colspan="5" class="border-default border-b px-4 py-2">
                    <div
                      class="bg-positive-dimmer/30 flex flex-col gap-1.5 rounded-md px-3 py-2 text-xs"
                    >
                      {#if run.output_payload_json.structured}
                        {@const structured = run.output_payload_json.structured}
                        {#if Array.isArray(structured)}
                          <div class="text-secondary flex flex-wrap items-baseline gap-x-3 gap-y-1">
                            <span class="text-positive-stronger font-semibold"
                              >{m.flow_run_output()}:</span
                            >
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
                            <span class="text-positive-stronger font-semibold"
                              >{m.flow_run_output()}:</span
                            >
                            {#each entries as [key, val] (key)}
                              <span>
                                <span class="text-positive-stronger font-semibold">{key}:</span>
                                <span class="text-secondary"
                                  >{String(val).slice(0, 80)}{String(val).length > 80
                                    ? "\u2026"
                                    : ""}</span
                                >
                              </span>
                            {/each}
                            {#if Object.keys(structured).length > 4}
                              <span class="text-muted"
                                >+{Object.keys(structured).length - 4} more</span
                              >
                            {/if}
                          </div>
                        {/if}
                      {:else if run.output_payload_json.text && !run.output_payload_json.artifacts?.length}
                        <div class="text-secondary truncate">
                          <span class="text-positive-stronger font-semibold"
                            >{m.flow_run_output()}:</span
                          >
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
                              class="group border-default bg-primary inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium shadow-sm transition-all hover:shadow"
                              onclick={() => downloadArtifact(run.id, artifact.file_id)}
                            >
                              <IconArrowDownToLine
                                class="text-muted group-hover:text-secondary size-3"
                              />
                              {artifact.name}
                            </button>
                          {/each}
                        </div>
                      {/if}
                    </div>
                  </td>
                </tr>
              {/if}
              {#if selectedRunId === run.id}
                <tr>
                  <td
                    id={getEvidenceRowId(run.id)}
                    colspan="5"
                    class="border-default bg-hover-dimmer/50 border-b px-2 py-3"
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
                  </td>
                </tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</div>

<AlertDialog.Root bind:open={showCancelConfirm}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.cancel()}</AlertDialog.Title>
      <AlertDialog.Description>{m.flow_run_cancel_confirm()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action onclick={confirmCancelRun}>{m.cancel()}</AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
