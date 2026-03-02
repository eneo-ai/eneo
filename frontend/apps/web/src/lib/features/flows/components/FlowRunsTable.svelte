<script lang="ts">
  import type { Flow, FlowRun, Intric } from "@intric/intric-js";
  import { Button } from "@intric/ui";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import FlowRunDialog from "./FlowRunDialog.svelte";
  import FlowRunEvidence from "./FlowRunEvidence.svelte";
  import { onDestroy } from "svelte";
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
      case "completed": return "bg-green-100 text-green-700";
      case "failed": return "bg-red-100 text-red-700";
      case "running": return "bg-blue-100 text-blue-700";
      case "queued": return "bg-gray-100 text-gray-700";
      case "cancelled": return "bg-amber-100 text-amber-700";
      default: return "bg-gray-100 text-gray-700";
    }
  }

  function getStatusLabel(status: string): string {
    const map: Record<string, () => string> = {
      completed: m.flow_run_status_completed,
      failed: m.flow_run_status_failed,
      queued: m.flow_run_status_queued,
      running: m.flow_run_status_running,
    };
    return (map[status] ?? (() => status))();
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
    }
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
      <Button variant="ghost" size="sm" on:click={loadRuns} class="gap-1.5 text-xs">
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
            <tr class="border-default border-b bg-slate-50/80 text-left dark:bg-slate-800/30">
              <th scope="col" class="px-4 py-2 font-medium">{m.status()}</th>
              <th scope="col" class="px-4 py-2 font-medium">{m.version()}</th>
              <th scope="col" class="px-4 py-2 font-medium">{m.flow_run_started()}</th>
              <th scope="col" class="px-4 py-2 font-medium">{m.duration()}</th>
              <th scope="col" class="px-4 py-2 font-medium">{m.actions()}</th>
            </tr>
          </thead>
          <tbody>
            {#each runs as run (run.id)}
              <tr class="border-default border-b last:border-b-0 transition-colors hover:bg-hover-dimmer">
                <td class="px-4 py-2">
                  <span class="{getStatusColor(run.status)} inline-flex rounded-full px-2 py-0.5 text-xs font-medium">
                    {getStatusLabel(run.status)}
                  </span>
                </td>
                <td class="px-4 py-2 tabular-nums text-secondary">v{run.flow_version}</td>
                <td class="px-4 py-2 text-secondary">
                  {new Date(run.created_at).toLocaleString()}
                </td>
                <td class="px-4 py-2 tabular-nums text-secondary">
                  {#if run.status === "completed" || run.status === "failed"}
                    {formatDuration(run.created_at, run.updated_at)}
                  {:else if run.status === "running"}
                    <span class="text-blue-600">{m.flow_run_running()}</span>
                  {:else}
                    -
                  {/if}
                </td>
                <td class="px-4 py-2">
                  <div class="flex items-center gap-1">
                    <Button
                      variant="outlined"
                      size="sm"
                      on:click={() => (selectedRunId = selectedRunId === run.id ? null : run.id)}
                    >
                      {m.flow_run_evidence()}
                    </Button>
                    {#if run.status === "queued" || run.status === "running"}
                      <Button
                        variant="destructive"
                        size="sm"
                        on:click={async () => {
                          await intric.flows.runs.cancel({ id: run.id });
                          await loadRuns();
                        }}
                      >
                        {m.cancel()}
                      </Button>
                    {/if}
                  </div>
                </td>
              </tr>
              {#if run.status === "failed" && run.error_message}
                <tr>
                  <td colspan="5" class="border-default border-b px-4 py-2">
                    <div class="flex min-w-0 items-start gap-2 rounded bg-red-50 px-3 py-2 text-xs text-red-700">
                      <span class="shrink-0 font-medium">{m.flow_run_error()}:</span>
                      <span class="min-w-0 break-words">{run.error_message}</span>
                    </div>
                  </td>
                </tr>
              {/if}
              {#if run.status === "completed" && run.output_payload_json}
                <tr>
                  <td colspan="5" class="border-default border-b px-4 py-2">
                    <div class="flex flex-col gap-1.5 rounded bg-green-50 px-3 py-2 text-xs">
                      {#if run.output_payload_json.structured}
                        {@const entries = Object.entries(run.output_payload_json.structured).slice(0, 4)}
                        <div class="text-secondary flex flex-wrap gap-x-3 gap-y-1">
                          <span class="font-medium text-green-700">{m.flow_run_output()}:</span>
                          {#each entries as [key, val], i}
                            <span>
                              <span class="font-medium text-green-700">{key}:</span>
                              {String(val).slice(0, 80)}{String(val).length > 80 ? "\u2026" : ""}{i < entries.length - 1 ? "" : ""}
                            </span>
                          {/each}
                          {#if Object.keys(run.output_payload_json.structured).length > 4}
                            <span class="text-muted">+{Object.keys(run.output_payload_json.structured).length - 4} more</span>
                          {/if}
                        </div>
                      {:else if run.output_payload_json.text}
                        <div class="text-secondary truncate">
                          <span class="font-medium text-green-700">{m.flow_run_output()}:</span>
                          {String(run.output_payload_json.text).slice(0, 200)}{String(run.output_payload_json.text).length > 200 ? "\u2026" : ""}
                        </div>
                      {/if}
                      {#if run.output_payload_json.artifacts?.length}
                        <div class="flex flex-wrap items-center gap-2">
                          {#each run.output_payload_json.artifacts as artifact}
                            <button
                              class="inline-flex items-center gap-1 rounded-md border border-green-200 bg-white px-2 py-1 text-xs font-medium text-green-700 hover:bg-green-100 transition-colors"
                              on:click={() => downloadArtifact(artifact.file_id)}
                            >
                              {m.download()} {artifact.name}
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
                  <td colspan="5" class="bg-hover-dimmer px-4 py-4">
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
