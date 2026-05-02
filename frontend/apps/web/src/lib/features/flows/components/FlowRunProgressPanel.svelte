<script lang="ts">
  import type { FlowGraph, FlowRunStep, Intric } from "@intric/intric-js";
  import { onMount, untrack } from "svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import FlowRunProgressView from "./FlowRunProgressView.svelte";
  import { buildFlowRunProgressSnapshot, type FlowRunProgressSnapshot } from "./flowRunProgress";
  import { isFlowRunActive } from "./flowRunStatusSets";

  const POLL_INTERVAL_MS = 3000;
  const STALE_WARNING_THRESHOLD = 3;

  let {
    runId,
    flowId,
    eneo,
    runStatus,
    runStartedAt = null,
    initialSnapshot = null,
    onSnapshotUpdate
  }: {
    runId: string;
    flowId: string;
    eneo: Intric;
    runStatus: string;
    runStartedAt?: string | null;
    initialSnapshot?: FlowRunProgressSnapshot | null;
    onSnapshotUpdate?: (snapshot: FlowRunProgressSnapshot) => void;
  } = $props();

  let loading = $state(untrack(() => initialSnapshot === null));
  let loadError: string | null = $state(null);
  let graphSnapshot: FlowGraph | null = $state(null);
  let snapshot: FlowRunProgressSnapshot = $state(untrack(() => initialSnapshot ?? { steps: [] }));
  let pollFailureCount = $state(0);
  let pollTimeout: ReturnType<typeof setTimeout> | null = null;
  let isPolling = $state(false);

  async function fetchGraphSnapshot() {
    return await eneo.flows.graph({ id: flowId, run_id: runId });
  }

  async function fetchStepStatuses() {
    return await eneo.flows.runs.steps({ flowId, runId });
  }

  function applySnapshot({ graph, steps }: { graph: FlowGraph | null; steps: FlowRunStep[] }) {
    graphSnapshot = graph;
    snapshot = buildFlowRunProgressSnapshot(graphSnapshot, steps);
    onSnapshotUpdate?.(snapshot);
  }

  async function loadInitial() {
    loading = snapshot.steps.length === 0;
    loadError = null;
    try {
      const [graph, steps] = await Promise.all([fetchGraphSnapshot(), fetchStepStatuses()]);
      applySnapshot({ graph, steps });
      pollFailureCount = 0;
    } catch (error) {
      console.error("Failed to load live run progress", error);
      loadError = error instanceof Error ? error.message : "Failed to load run progress";
    } finally {
      loading = false;
    }
  }

  async function pollStepStatuses() {
    if (isPolling) return;
    isPolling = true;
    try {
      const steps = await fetchStepStatuses();
      applySnapshot({ graph: graphSnapshot, steps });
      pollFailureCount = 0;
    } catch (error) {
      console.error("Failed to refresh live run progress", error);
      pollFailureCount += 1;
    } finally {
      isPolling = false;
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

  $effect(() => {
    const active = isFlowRunActive(runStatus);
    if (active && pollTimeout === null) {
      const scheduleNextPoll = () => {
        pollTimeout = setTimeout(async () => {
          await pollStepStatuses();
          pollTimeout = null;
          if (isFlowRunActive(runStatus)) {
            scheduleNextPoll();
          }
        }, POLL_INTERVAL_MS);
      };
      scheduleNextPoll();
    } else if (!active && pollTimeout !== null) {
      clearTimeout(pollTimeout);
      pollTimeout = null;
    }
  });

  $effect(() => {
    return () => {
      if (pollTimeout !== null) {
        clearTimeout(pollTimeout);
      }
    };
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
  <FlowRunProgressView
    {snapshot}
    stale={pollFailureCount >= STALE_WARNING_THRESHOLD}
    {runStartedAt}
    onRefresh={() => void pollStepStatuses()}
    onDownloadArtifact={downloadArtifact}
  />
{/if}
