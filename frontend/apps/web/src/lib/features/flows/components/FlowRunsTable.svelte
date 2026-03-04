<script lang="ts">
  import type { Flow, FlowRun, Intric } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconArrowDownToLine } from "@intric/icons/arrow-down-to-line";
  import FlowRunDialog from "./FlowRunDialog.svelte";
  import FlowRunEvidence from "./FlowRunEvidence.svelte";
  import { onDestroy } from "svelte";
  import { toast } from "$lib/components/toast";
  import { getFlowRunStatusLabel } from "./flowRunStatusLabel";
  import { getRedispatchToastKind } from "./flowRunRedispatchFeedback";
  import { m } from "$lib/paraglide/messages";

  export let flow: Flow;
  export let intric: Intric;
  export let visible = true;
  export let reloadTrigger = 0;

  let runs: FlowRun[] = [];
  let loading = true;
  let loadError: string | null = null;
  let showRunDialog = false;
  let selectedRunId: string | null = null;
  let lastLoadedFlowId: string | null = null;
  let isInitialLoad = true;
  let redispatchingRunId: string | null = null;
  let cancellingRunId: string | null = null;
  let showCancelConfirm: Dialog.OpenState;
  let pendingCancelRunId: string | null = null;

  async function loadRuns() {
    if (!flow?.id) {
      runs = [];
      loading = false;
      return;
    }
    if (isInitialLoad) loading = true;
    loadError = null;
    try {
      const result = await intric.flows.runs.list({ flowId: flow.id });
      runs = (result.items ?? result) as FlowRun[];
      isInitialLoad = false;
    } catch (e) {
      console.error("Error loading flow runs", e);
      loadError = e instanceof Error ? e.message : "Failed to load runs";
    } finally {
      loading = false;
    }
  }

  $: if (flow?.id && flow.id !== lastLoadedFlowId) {
    lastLoadedFlowId = flow.id;
    void loadRuns();
  } else if (!flow?.id) {
    lastLoadedFlowId = null;
    loading = false;
  }

  $: if (reloadTrigger) { void loadRuns(); }

  // Poll for updates every 5s when there are running runs
  let pollInterval: ReturnType<typeof setInterval> | null = null;
  $: hasActiveRuns = runs.some((r) => r.status === "queued" || r.status === "running");
  $: if (hasActiveRuns && !pollInterval && visible) {
    pollInterval = setInterval(loadRuns, 5000);
  } else if ((!hasActiveRuns || !visible) && pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }

  onDestroy(() => {
    if (pollInterval) clearInterval(pollInterval);
  });

  function getStatusColor(status: string): string {
    switch (status) {
      case "completed": return "text-positive-stronger";
      case "failed": return "text-negative-stronger";
      case "running": return "text-accent-stronger";
      case "queued": return "text-secondary";
      case "cancelled": return "text-warning-stronger";
      default: return "text-secondary";
    }
  }

  function getStatusDotColor(status: string): string {
    switch (status) {
      case "completed": return "bg-positive-default";
      case "failed": return "bg-negative-default";
      case "running": return "bg-accent-default animate-pulse";
      case "queued": return "bg-secondary";
      case "cancelled": return "bg-warning-default";
      default: return "bg-secondary";
    }
  }

  function getStatusLabel(status: string): string {
    return getFlowRunStatusLabel(status, {
      completed: m.flow_run_status_completed,
      failed: m.flow_run_status_failed,
      queued: m.flow_run_status_queued,
      running: m.flow_run_status_running,
      cancelled: m.flow_run_status_cancelled,
    });
  }

  function formatDuration(start: string, end: string): string {
    const ms = new Date(end).getTime() - new Date(start).getTime();
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  }

  async function downloadArtifact(fileId: string) {
    try {
      const { url } = await intric.files.generateSignedUrl({
        fileId,
        contentDisposition: "attachment",
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
      const result = await intric.flows.runs.redispatch({ id: runId });
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
    $showCancelConfirm = true;
  }

  async function confirmCancelRun() {
    if (!pendingCancelRunId) return;
    const runId = pendingCancelRunId;
    $showCancelConfirm = false;
    pendingCancelRunId = null;
    cancellingRunId = runId;
    try {
      await intric.flows.runs.cancel({ id: runId });
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
</script>

<div class="flex flex-col gap-4 p-4">
  <div class="flex items-center justify-between">
    <h2 class="text-lg font-semibold">{m.flow_history()}</h2>
    <div class="flex items-center gap-2">
      {#if flow.published_version != null}
        <Button variant="primary" on:click={() => (showRunDialog = true)}>
          {m.flow_run_trigger()}
        </Button>
      {/if}
    </div>
  </div>

  {#if loading}
    <div class="flex items-center justify-center gap-2 py-8 text-sm text-secondary">
      <IconLoadingSpinner class="size-4 animate-spin" />
      {m.flow_loading()}
    </div>
  {:else if loadError}
    <div class="flex items-center gap-3 rounded-lg border border-negative-default/20 bg-negative-dimmer px-5 py-4">
      <p class="flex-1 text-sm text-negative-default">{loadError}</p>
      <Button variant="outlined" size="sm" on:click={loadRuns} class="gap-1.5 text-xs">
        {m.flow_retry()}
      </Button>
    </div>
  {:else if runs.length === 0}
    <p class="text-secondary py-8 text-center text-sm">{m.flow_no_runs_yet()}</p>
  {:else}
    <div class="border-default overflow-hidden rounded-lg border">
      <div class="overflow-x-auto">
        <table class="w-full min-w-[600px] text-sm" aria-label={m.flow_history()}>
          <thead>
            <tr class="border-default border-b text-left">
              <th scope="col" class="px-4 py-2.5 text-xs font-medium text-muted">{m.status()}</th>
              <th scope="col" class="px-4 py-2.5 text-xs font-medium text-muted">{m.version()}</th>
              <th scope="col" class="px-4 py-2.5 text-xs font-medium text-muted">{m.flow_run_started()}</th>
              <th scope="col" class="px-4 py-2.5 text-xs font-medium text-muted">{m.duration()}</th>
              <th scope="col" class="px-4 py-2.5 text-xs font-medium text-muted">{m.actions()}</th>
            </tr>
          </thead>
          <tbody>
            {#each runs as run (run.id)}
              <tr
                class="border-dimmer border-b last:border-b-0 cursor-pointer transition-colors hover:bg-hover-dimmer"
                class:bg-hover-dimmer={selectedRunId === run.id}
                tabindex="0"
                on:click={() => (selectedRunId = selectedRunId === run.id ? null : run.id)}
                on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectedRunId = selectedRunId === run.id ? null : run.id; } }}
                style:border-left={selectedRunId === run.id ? "2px solid var(--accent-default)" : undefined}
              >
                <td class="px-4 py-3">
                  <span class="{getStatusColor(run.status)} inline-flex items-center gap-1.5 text-xs font-medium">
                    <span class="{getStatusDotColor(run.status)} size-1.5 shrink-0 rounded-full"></span>
                    {getStatusLabel(run.status)}
                  </span>
                </td>
                <td class="px-4 py-3 tabular-nums text-secondary">v{run.flow_version}</td>
                <td class="px-4 py-3 text-secondary">
                  {new Date(run.created_at).toLocaleString()}
                </td>
                <td class="px-4 py-3 tabular-nums text-secondary">
                  {#if run.status === "completed" || run.status === "failed"}
                    {formatDuration(run.created_at, run.updated_at)}
                  {:else if run.status === "running"}
                    <span class="text-accent-stronger">{m.flow_run_running()}</span>
                  {:else}
                    -
                  {/if}
                </td>
                <td class="px-4 py-2" on:click|stopPropagation>
                  <div class="flex items-center gap-1">
                    <Button
                      variant="outlined"
                      size="sm"
                      aria-expanded={selectedRunId === run.id}
                      aria-controls={getEvidenceRowId(run.id)}
                      on:click={() => (selectedRunId = selectedRunId === run.id ? null : run.id)}
                    >
                      {m.flow_run_evidence()}
                    </Button>
                    {#if run.status === "queued"}
                      <Button
                        variant="outlined"
                        size="sm"
                        disabled={redispatchingRunId === run.id}
                        on:click={() => void redispatchRun(run.id)}
                      >
                        {redispatchingRunId === run.id ? m.flow_run_redispatching() : m.flow_run_redispatch()}
                      </Button>
                    {/if}
                    {#if run.status === "queued" || run.status === "running"}
                      <Button
                        variant="destructive"
                        size="sm"
                        disabled={cancellingRunId === run.id}
                        on:click={() => requestCancelRun(run.id)}
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
                    <div class="flex min-w-0 items-start gap-2 rounded-md border-l-2 border-l-negative-default bg-hover-dimmer px-3 py-2 text-xs text-negative-stronger">
                      <span class="shrink-0 font-semibold">{m.flow_run_error()}:</span>
                      <span class="min-w-0 break-words">{run.error_message}</span>
                    </div>
                  </td>
                </tr>
              {/if}
              {#if run.status === "completed" && run.output_payload_json}
                <tr>
                  <td colspan="5" class="border-default border-b px-4 py-2">
                    <div class="flex flex-col gap-1.5 rounded-md border-l-2 border-l-positive-default bg-hover-dimmer px-3 py-2 text-xs">
                      {#if run.output_payload_json.structured}
                        {@const structured = run.output_payload_json.structured}
                        {#if Array.isArray(structured)}
                          <div class="text-secondary flex flex-wrap items-baseline gap-x-3 gap-y-1">
                            <span class="font-semibold text-positive-stronger">{m.flow_run_output()}:</span>
                            {#each structured.slice(0, 3) as item, i}
                              <span class="font-mono">
                                #{i + 1}: {JSON.stringify(item).slice(0, 80)}{JSON.stringify(item).length > 80 ? "\u2026" : ""}
                              </span>
                            {/each}
                            {#if structured.length > 3}
                              <span class="text-muted">+{structured.length - 3} more</span>
                            {/if}
                          </div>
                        {:else}
                          {@const entries = Object.entries(structured).slice(0, 4)}
                          <div class="text-secondary flex flex-wrap items-baseline gap-x-4 gap-y-1">
                            <span class="font-semibold text-positive-stronger">{m.flow_run_output()}:</span>
                            {#each entries as [key, val], i}
                              <span>
                                <span class="font-semibold text-positive-stronger">{key}:</span>
                                <span class="text-secondary">{String(val).slice(0, 80)}{String(val).length > 80 ? "\u2026" : ""}</span>
                              </span>
                            {/each}
                            {#if Object.keys(structured).length > 4}
                              <span class="text-muted">+{Object.keys(structured).length - 4} more</span>
                            {/if}
                          </div>
                        {/if}
                      {:else if run.output_payload_json.text}
                        <div class="text-secondary truncate">
                          <span class="font-semibold text-positive-stronger">{m.flow_run_output()}:</span>
                          {String(run.output_payload_json.text).slice(0, 200)}{String(run.output_payload_json.text).length > 200 ? "\u2026" : ""}
                        </div>
                      {/if}
                      {#if run.output_payload_json.artifacts?.length}
                        <div class="flex flex-wrap items-center gap-2">
                          {#each run.output_payload_json.artifacts as artifact}
                            <button
                              class="group inline-flex items-center gap-1.5 rounded-md border border-default bg-primary px-2.5 py-1 text-xs font-medium shadow-sm transition-all hover:shadow"
                              on:click={() => downloadArtifact(artifact.file_id)}
                            >
                              <IconArrowDownToLine class="size-3 text-muted group-hover:text-secondary" />
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
                  <td id={getEvidenceRowId(run.id)} colspan="5" class="border-default border-b bg-hover-dimmer/50 px-4 py-4">
                    <FlowRunEvidence runId={run.id} {intric} runStatus={run.status} />
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

<FlowRunDialog
  bind:open={showRunDialog}
  {flow}
  {intric}
  lastInputPayload={runs.length > 0 ? (runs[0].input_payload_json ?? null) : null}
  on:runCreated={loadRuns}
/>

<Dialog.Root alert bind:isOpen={showCancelConfirm}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.cancel()}</Dialog.Title>
    <Dialog.Description>{m.flow_run_cancel_confirm()}</Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close} variant="outlined">{m.cancel()}</Button>
      <Button variant="destructive" on:click={confirmCancelRun}>{m.cancel()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
