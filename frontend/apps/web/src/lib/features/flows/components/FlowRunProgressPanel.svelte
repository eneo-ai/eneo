<script lang="ts">
  import { type FlowGraph, type FlowRunStep, type Eneo } from "@eneo/eneo-js";
  import { onMount, untrack } from "svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import FlowRunProgressView from "./FlowRunProgressView.svelte";
  import { buildFlowRunProgressSnapshot, type FlowRunProgressSnapshot } from "./flowRunProgress";

  let {
    runId,
    flowId,
    eneo,
    runStartedAt = null,
    initialSnapshot = null,
    refreshTick = 0,
    onSnapshotUpdate
  }: {
    runId: string;
    flowId: string;
    eneo: Eneo;
    runStartedAt?: string | null;
    initialSnapshot?: FlowRunProgressSnapshot | null;
    /** Bumped by the owner on every run-list poll; each bump re-reads step statuses. */
    refreshTick?: number;
    onSnapshotUpdate?: (snapshot: FlowRunProgressSnapshot) => void;
  } = $props();

  let loading = $state(untrack(() => initialSnapshot === null));
  let loadError: string | null = $state(null);
  let refreshFailed = $state(false);
  let refreshing = $state(false);
  let graphSnapshot: FlowGraph | null = $state(null);
  let stepSnapshot: FlowRunStep[] = $state([]);
  let snapshot: FlowRunProgressSnapshot = $state(untrack(() => initialSnapshot ?? { steps: [] }));

  async function fetchGraphSnapshot() {
    return await eneo.flows.graph({ id: flowId, run_id: runId });
  }

  async function fetchStepStatuses() {
    return await eneo.flows.runs.steps({ flowId, runId });
  }

  // Every read is numbered when it starts; a response is applied only if no
  // later read has been applied already, so a slow background read cannot
  // roll a fresher status (or a manual refresh) back.
  let issuedReads = 0;
  let appliedRead = 0;

  function applySnapshot(
    read: number,
    { graph, steps }: { graph: FlowGraph | null; steps: FlowRunStep[] }
  ): boolean {
    if (read <= appliedRead) return false;
    appliedRead = read;
    graphSnapshot = graph;
    stepSnapshot = steps;
    snapshot = buildFlowRunProgressSnapshot(graphSnapshot, steps);
    onSnapshotUpdate?.(snapshot);
    return true;
  }

  // Step statuses ride the run-pinned graph, which is not an audited content
  // read, so they can follow the list poll. Outputs (the audited step list)
  // stay on demand: initial open and "Uppdatera nu". A status that moved on
  // since the outputs were read leaves that step's details marked stale.
  let refreshingStatuses = false;
  async function refreshStepStatusesFromGraph() {
    if (refreshingStatuses || loading) return;
    refreshingStatuses = true;
    const read = ++issuedReads;
    try {
      const graph = await fetchGraphSnapshot();
      if (applySnapshot(read, { graph, steps: stepSnapshot })) refreshFailed = false;
    } catch (error) {
      console.error("Failed to refresh run step statuses", error);
      // The snapshot stays; the panel says it may be behind the row.
      refreshFailed = true;
    } finally {
      refreshingStatuses = false;
    }
  }

  $effect(() => {
    if (refreshTick === 0) return;
    untrack(() => void refreshStepStatusesFromGraph());
  });

  async function loadInitial() {
    loading = snapshot.steps.length === 0;
    loadError = null;
    const read = ++issuedReads;
    try {
      const [graph, steps] = await Promise.all([fetchGraphSnapshot(), fetchStepStatuses()]);
      applySnapshot(read, { graph, steps });
    } catch (error) {
      console.error("Failed to load live run progress", error);
      loadError = m.flow_run_progress_load_failed();
    } finally {
      loading = false;
    }
  }

  async function refreshStepStatuses() {
    if (refreshing) return;
    refreshing = true;
    const read = ++issuedReads;
    try {
      const [graph, steps] = await Promise.all([fetchGraphSnapshot(), fetchStepStatuses()]);
      if (applySnapshot(read, { graph, steps })) refreshFailed = false;
    } catch (error) {
      console.error("Failed to refresh live run progress", error);
      refreshFailed = true;
    } finally {
      refreshing = false;
    }
  }

  async function downloadArtifact(fileId: string) {
    try {
      const { url } = await eneo.flows.runs.artifactSignedUrl({
        flowId,
        runId,
        fileId,
        contentDisposition: "attachment"
      });
      window.open(url, "_blank");
    } catch (error) {
      console.error("Failed to download artifact", error);
      toast.error(m.flow_run_download_artifact_failed());
    }
  }

  onMount(() => {
    void loadInitial();
  });
</script>

{#if loading && snapshot.steps.length === 0}
  <div class="flex flex-col gap-4">
    <div class="flex flex-col gap-2.5">
      <div class="flex items-center justify-between">
        <Skeleton class="h-4 w-40" />
        <Skeleton class="h-3 w-20" />
      </div>
      <Skeleton class="h-1.5 w-full" />
    </div>
    <div class="flex flex-col gap-3">
      {#each Array(3) as _, i (i)}
        <Skeleton class="h-14 w-full rounded-lg" />
      {/each}
    </div>
  </div>
{:else if loadError}
  <Alert.Root variant="destructive" class="flex items-center gap-3 px-5 py-4">
    <Alert.Description class="flex-1 text-sm">{loadError}</Alert.Description>
    <Button variant="outline" size="sm" onclick={() => void loadInitial()} class="gap-1.5 text-xs">
      {m.flow_retry()}
    </Button>
  </Alert.Root>
{:else}
  <div class="flex flex-wrap items-center justify-between gap-2">
    <p class="text-muted max-w-2xl text-xs leading-relaxed">
      {m.flow_run_progress_manual_refresh()}
    </p>
    <Button
      variant="outline"
      size="sm"
      disabled={refreshing}
      onclick={() => void refreshStepStatuses()}
    >
      {m.flow_run_progress_refresh()}
    </Button>
  </div>
  {#if refreshFailed}
    <Alert.Root variant="destructive" class="mt-3">
      <Alert.Description>{m.flow_run_progress_refresh_failed()}</Alert.Description>
    </Alert.Root>
  {/if}
  <FlowRunProgressView {snapshot} {runStartedAt} onDownloadArtifact={downloadArtifact} />
{/if}
