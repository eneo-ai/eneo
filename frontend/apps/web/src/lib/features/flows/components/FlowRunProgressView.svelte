<script lang="ts">
  import { fly, fade, slide } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { browser } from "$app/environment";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { serializeEvidencePayload } from "./flowRunEvidenceActions";
  import FlowRunProgressStepCard from "./FlowRunProgressStepCard.svelte";
  import {
    formatFlowRunElapsed,
    getFlowRunProgressStats,
    type FlowRunProgressSnapshot
  } from "./flowRunProgress";

  const prefersReducedMotion =
    browser && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let {
    snapshot,
    stale = false,
    loadingTerminalDetails = false,
    runStartedAt = null,
    onRefresh,
    onDownloadArtifact
  }: {
    snapshot: FlowRunProgressSnapshot;
    stale?: boolean;
    loadingTerminalDetails?: boolean;
    runStartedAt?: string | null;
    onRefresh?: () => void;
    onDownloadArtifact?: (fileId: string) => Promise<void>;
  } = $props();

  let userToggles: Record<number, boolean> = $state({});
  let expandedInputSteps: number[] = $state([]);
  let copiedKey: string | null = $state(null);
  let copiedTimer: ReturnType<typeof setTimeout> | null = null;
  let now = $state(Date.now());
  let tickInterval: ReturnType<typeof setInterval> | null = null;

  const stats = $derived(getFlowRunProgressStats(snapshot));
  const elapsedLabel = $derived(formatFlowRunElapsed(runStartedAt, now));
  const progressPercent = $derived(Math.round(stats.progressRatio * 100));

  const autoExpandedOrders = $derived(
    new Set(
      snapshot.steps
        .filter((step) => step.status !== "pending" && step.status !== "queued")
        .map((step) => step.stepOrder)
    )
  );

  function isStepExpanded(stepOrder: number): boolean {
    const toggled = userToggles[stepOrder];
    if (toggled !== undefined) return toggled;
    return autoExpandedOrders.has(stepOrder);
  }

  $effect(() => {
    const shouldTick = Boolean(runStartedAt) && stats.running > 0;

    if (!shouldTick) {
      if (tickInterval) {
        clearInterval(tickInterval);
        tickInterval = null;
      }
      return;
    }

    now = Date.now();
    tickInterval = setInterval(() => {
      now = Date.now();
    }, 1000);

    return () => {
      if (tickInterval) {
        clearInterval(tickInterval);
        tickInterval = null;
      }
    };
  });

  $effect(() => {
    return () => {
      if (copiedTimer) clearTimeout(copiedTimer);
    };
  });

  function toggleStep(order: number) {
    const currentlyExpanded = isStepExpanded(order);
    userToggles = { ...userToggles, [order]: !currentlyExpanded };
  }

  function toggleInputExpand(order: number) {
    expandedInputSteps = expandedInputSteps.includes(order)
      ? expandedInputSteps.filter((item) => item !== order)
      : [...expandedInputSteps, order];
  }

  function setCopied(key: string) {
    copiedKey = key;
    if (copiedTimer) clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => {
      copiedKey = null;
    }, 1200);
  }

  async function copyPayload(key: string, payload: unknown) {
    try {
      await navigator.clipboard.writeText(serializeEvidencePayload(payload));
      setCopied(key);
    } catch (error) {
      console.error("Could not copy flow run progress payload", error);
      toast.error(m.flow_run_copy_failed());
    }
  }

  async function handleDownloadArtifact(fileId: string) {
    if (!onDownloadArtifact) return;
    try {
      await onDownloadArtifact(fileId);
    } catch (error) {
      console.error("Could not download artifact from progress view", error);
    }
  }

  function getStepPanelId(stepOrder: number): string {
    return `flow-run-progress-panel-step-${stepOrder}`;
  }

  const headerSummary = $derived.by(() => {
    if (stats.total === 0) return m.flow_run_progress_waiting_for_run();
    if (stats.running > 0) return m.flow_run_progress_running_summary();
    if (stats.terminal === stats.total) return m.flow_run_status_completed();
    return m.flow_run_progress_pending_summary();
  });
</script>

<div class="flex flex-col gap-4">
  {#if stats.total > 0}
    <div class="flex flex-col gap-2.5">
      <div class="flex items-baseline justify-between gap-3">
        <div class="flex items-baseline gap-2">
          <span class="text-primary text-sm font-semibold tabular-nums">
            {m.flow_run_progress_counter({
              current: String(stats.terminal + stats.running),
              total: String(stats.total)
            })}
          </span>
          <span class="text-muted text-xs">&middot;</span>
          <span class="text-secondary text-xs">{headerSummary}</span>
        </div>
        {#if elapsedLabel}
          <span class="text-muted shrink-0 text-xs tabular-nums">
            {m.flow_run_progress_elapsed({ elapsed: elapsedLabel })}
          </span>
        {/if}
      </div>
      <div
        class="bg-hover-dimmer h-1.5 w-full overflow-hidden rounded-full"
        role="progressbar"
        aria-valuenow={progressPercent}
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <div
          class="{progressPercent >= 100
            ? 'bg-positive-default'
            : 'bg-accent-default'} h-full w-full origin-left rounded-full transition-transform duration-500 ease-out"
          style:transform="scaleX({Math.max(0, Math.min(1, progressPercent / 100))})"
        ></div>
      </div>
    </div>
  {/if}

  {#if stale}
    <div transition:slide={{ duration: prefersReducedMotion ? 0 : 200, easing: cubicOut }}>
      <Alert.Root class="flex items-center gap-3">
        <Alert.Description class="flex-1 text-sm">{m.flow_run_progress_stale()}</Alert.Description>
        {#if onRefresh}
          <Button
            variant="outline"
            size="sm"
            class="h-7 shrink-0 text-xs"
            onclick={() => onRefresh?.()}
          >
            {m.flow_run_progress_refresh()}
          </Button>
        {/if}
      </Alert.Root>
    </div>
  {/if}

  {#if loadingTerminalDetails}
    <div
      class="text-secondary flex items-center gap-2 text-xs"
      in:fade={{ duration: prefersReducedMotion ? 0 : 200 }}
    >
      <IconLoadingSpinner class="size-3.5 animate-spin" />
      {m.flow_run_progress_loading_terminal()}
    </div>
  {/if}

  <div class="flex flex-col gap-3">
    {#each snapshot.steps as step (step.stepOrder)}
      <div
        in:fly={{
          y: prefersReducedMotion ? 0 : 6,
          duration: prefersReducedMotion ? 0 : 200,
          delay: prefersReducedMotion ? 0 : step.stepOrder * 50,
          easing: cubicOut
        }}
      >
        <FlowRunProgressStepCard
          {step}
          expanded={isStepExpanded(step.stepOrder)}
          inputExpanded={expandedInputSteps.includes(step.stepOrder)}
          {copiedKey}
          panelId={getStepPanelId(step.stepOrder)}
          onToggle={toggleStep}
          onToggleInput={toggleInputExpand}
          onCopyPayload={copyPayload}
          onDownloadArtifact={handleDownloadArtifact}
        />
      </div>
    {/each}
  </div>
</div>
