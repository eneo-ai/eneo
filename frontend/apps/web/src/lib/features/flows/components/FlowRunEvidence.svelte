<svelte:options runes={false} />

<script lang="ts">
  import type { FlowRunDebugExport, Intric, FlowStepResult } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { onDestroy, onMount } from "svelte";
  import { toast } from "$lib/components/toast";
  import {
    downloadEvidenceExport,
    downloadJsonArtifact as triggerJsonDownload,
    serializeEvidencePayload
  } from "./flowRunEvidenceActions";
  import { getFlowRunStatusLabel } from "./flowRunStatusLabel";
  import { m } from "$lib/paraglide/messages";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import {
    getRuntimeInputSummary,
    getTemplateProvenanceSummary
  } from "$lib/features/flows/flowEvidenceProvenance";
  import { Alert } from "@eneo/ui";
  import FlowRunEvidenceToolbar from "./FlowRunEvidenceToolbar.svelte";
  import FlowRunEvidenceSummary from "./FlowRunEvidenceSummary.svelte";
  import FlowRunEvidenceStepCard from "./FlowRunEvidenceStepCard.svelte";

  export let runId: string;
  export let flowId: string;
  export let intric: Intric;
  export let runStatus: string;

  type EvidencePayload = {
    run: Record<string, unknown>;
    definition_snapshot: Record<string, unknown>;
    step_results: FlowStepResult[];
    step_attempts: Record<string, unknown>[];
    debug_export: FlowRunDebugExport;
  };

  type FlowRunTranscriptionTelemetry = {
    transcript_bytes?: number;
    estimated_tokens?: number;
    elapsed_ms?: number;
    files_count?: number;
    model?: string;
    language?: string;
    used_cache?: boolean;
    cached_files_count?: number;
  };

  let evidence: EvidencePayload | null = null;
  let loading = true;
  let loadError = false;
  let expandedSteps: number[] = [];
  let expandedInputSteps: number[] = [];
  let hasAutoExpanded = false;
  let copiedKey: string | null = null;
  let copiedTimer: ReturnType<typeof setTimeout> | null = null;
  const mode = getFlowUserMode();
  let stepAttemptsByOrder: Record<number, Record<string, unknown>[]> = {};
  let lastFetchedStatus: string | null = null;
  let pendingTerminalRefetchStatus: string | null = null;

  onMount(async () => {
    try {
      evidence = await intric.flows.runs.evidence({ id: runId, flowId });
    } catch (e) {
      console.error("Error loading evidence", e);
      loadError = true;
    }
    loading = false;
  });

  $: if (
    runStatus &&
    evidence &&
    lastFetchedStatus !== runStatus &&
    (runStatus === "completed" || runStatus === "failed" || runStatus === "cancelled")
  ) {
    lastFetchedStatus = runStatus;
    pendingTerminalRefetchStatus = runStatus;
  }

  $: if (evidence && evidence.step_results.length > 0 && !hasAutoExpanded) {
    hasAutoExpanded = true;
    expandedSteps = [evidence.step_results[0].step_order];
  }

  $: if (pendingTerminalRefetchStatus !== null) {
    pendingTerminalRefetchStatus = null;
    queueMicrotask(() => {
      void refetchEvidence();
    });
  }

  $: stepAttemptsByOrder = groupStepAttemptsByOrder(evidence?.step_attempts ?? []);

  async function refetchEvidence() {
    try {
      evidence = await intric.flows.runs.evidence({ id: runId, flowId });
    } catch {
      /* ignore — already have stale data */
    }
  }

  onDestroy(() => {
    if (copiedTimer) clearTimeout(copiedTimer);
  });

  function toggleStep(order: number) {
    expandedSteps = expandedSteps.includes(order)
      ? expandedSteps.filter((item) => item !== order)
      : [...expandedSteps, order];
  }

  function toggleInputExpand(order: number) {
    expandedInputSteps = expandedInputSteps.includes(order)
      ? expandedInputSteps.filter((item) => item !== order)
      : [...expandedInputSteps, order];
  }

  function getStatusColor(status: string): string {
    switch (status) {
      case "completed":
        return "text-positive-stronger";
      case "failed":
        return "text-negative-stronger";
      case "running":
        return "text-accent-stronger";
      case "pending":
        return "text-secondary";
      default:
        return "text-secondary";
    }
  }

  function getStatusDotColor(status: string): string {
    switch (status) {
      case "completed":
        return "bg-positive-default";
      case "failed":
        return "bg-negative-default";
      case "running":
        return "bg-accent-default animate-pulse";
      case "pending":
        return "bg-secondary";
      default:
        return "bg-secondary";
    }
  }

  function getStatusLabel(status: string): string {
    return getFlowRunStatusLabel(status, {
      completed: m.flow_run_status_completed,
      failed: m.flow_run_status_failed,
      queued: m.flow_run_status_queued,
      running: m.flow_run_status_running,
      cancelled: m.flow_run_status_cancelled
    });
  }

  function setCopied(key: string) {
    copiedKey = key;
    if (copiedTimer) clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => {
      copiedKey = null;
    }, 1200);
  }

  async function copyPayload(key: string, payload: unknown, failureMessage: string) {
    try {
      const rendered = serializeEvidencePayload(payload);
      await navigator.clipboard.writeText(rendered);
      setCopied(key);
    } catch (error) {
      console.error("Could not copy evidence payload", error);
      toast.error(failureMessage);
    }
  }

  function downloadJsonArtifact(fileName: string, payload: unknown, failureMessage: string) {
    try {
      triggerJsonDownload(fileName, payload);
    } catch (error) {
      console.error("Could not download evidence payload", error);
      toast.error(failureMessage);
    }
  }

  async function downloadCanonicalEvidenceExport() {
    try {
      await downloadEvidenceExport({ intric, flowId, runId });
    } catch (error) {
      console.error("Could not download canonical evidence export", error);
      toast.error(m.flow_run_download_evidence_export_failed());
    }
  }

  function getStepAttempts(stepOrder: number): Record<string, unknown>[] {
    return stepAttemptsByOrder[stepOrder] ?? [];
  }

  function groupStepAttemptsByOrder(
    attempts: Record<string, unknown>[],
  ): Record<number, Record<string, unknown>[]> {
    const grouped: Record<number, Record<string, unknown>[]> = {};
    for (const attempt of attempts) {
      const stepOrder = Number((attempt as { step_order?: unknown }).step_order ?? 0);
      grouped[stepOrder] ??= [];
      grouped[stepOrder].push(attempt);
    }
    return grouped;
  }

  function getStepDuration(stepOrder: number): string | null {
    const attempts = getStepAttempts(stepOrder);
    if (attempts.length === 0) return null;
    const first = attempts[0] as { started_at?: string; finished_at?: string };
    const last = attempts[attempts.length - 1] as { started_at?: string; finished_at?: string };
    if (!first.started_at || !last.finished_at) return null;
    const ms = new Date(last.finished_at).getTime() - new Date(first.started_at).getTime();
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  }

  async function downloadArtifact(fileId: string) {
    try {
      const { url } = await intric.flows.runs.artifactSignedUrl({
        flowId,
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

  function getStepPanelId(stepOrder: number): string {
    return `flow-run-step-panel-${runId}-${stepOrder}`;
  }

  function getStepRag(stepOrder: number) {
    const debugStep = evidence?.debug_export?.steps?.find((step) => step.step_order === stepOrder);
    return debugStep?.rag ?? null;
  }

  function getStepTranscription(result: FlowStepResult): FlowRunTranscriptionTelemetry | null {
    const payload = result.input_payload_json;
    if (payload === null || payload === undefined || typeof payload !== "object") {
      return null;
    }
    const raw = (payload as Record<string, unknown>).transcription;
    if (raw === null || raw === undefined || typeof raw !== "object" || Array.isArray(raw)) {
      return null;
    }
    return raw as FlowRunTranscriptionTelemetry;
  }

  function formatElapsedMs(value: number | undefined): string {
    if (value === undefined) return "—";
    if (value < 1000) return `${value}ms`;
    return `${(value / 1000).toFixed(1)}s`;
  }

  function formatBytes(value: number | undefined): string {
    if (value === undefined) return "—";
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  function getCacheStatusLabel(
    usedCache: boolean | undefined,
    cachedFilesCount: number | undefined,
    filesCount: number | undefined
  ): string {
    if (usedCache === true) return m.flow_run_transcription_cache_hit();
    if ((cachedFilesCount ?? 0) > 0 && (filesCount ?? 0) > 0) {
      return m.flow_run_transcription_cache_partial({
        cached: String(cachedFilesCount ?? 0),
        total: String(filesCount ?? 0)
      });
    }
    return m.flow_run_transcription_cache_miss();
  }

  function getRuntimeInputSummaryLabel(fileCount: number): string {
    return `${fileCount} ${fileCount === 1 ? "fil uppladdad" : "filer uppladdade"}`;
  }
</script>

{#if loading}
  <div class="text-secondary flex items-center gap-2 text-sm">
    <IconLoadingSpinner class="size-4 animate-spin" />
    {m.flow_run_evidence_loading()}
  </div>
{:else if loadError || evidence === null}
  <Alert.Root variant="destructive">
    <Alert.Description class="text-sm">{m.flow_run_evidence_error()}</Alert.Description>
  </Alert.Root>
{:else}
  <div class="flex flex-col gap-3">
    {#if $mode === "power_user"}
      <FlowRunEvidenceToolbar
        debugExport={evidence.debug_export}
        evidence={evidence}
        {copiedKey}
        onDownloadCanonicalEvidence={downloadCanonicalEvidenceExport}
        onCopyPayload={copyPayload}
        onDownloadJsonArtifact={downloadJsonArtifact}
      />
    {/if}

    <FlowRunEvidenceSummary
      runStatusLabel={getStatusLabel(runStatus)}
      statusColorClass={getStatusColor(runStatus)}
      traceId={evidence.debug_export?.run?.trace_id ?? null}
      redactionApplied={evidence.debug_export?.security?.redaction_applied === true}
    />

    {#each evidence.step_results as result (result.id ?? result.step_order)}
      {@const stepDef = ((evidence.definition_snapshot?.steps ?? []) as Record<string, unknown>[]).find(
        (step) => step.step_order === result.step_order
      )}
      <FlowRunEvidenceStepCard
        {result}
        {stepDef}
        duration={getStepDuration(result.step_order)}
        transcription={getStepTranscription(result)}
        runtimeInput={getRuntimeInputSummary(result.input_payload_json)}
        templateProvenance={getTemplateProvenanceSummary(result.output_payload_json)}
        stepRag={getStepRag(result.step_order)}
        stepAttempts={getStepAttempts(result.step_order)}
        {copiedKey}
        expanded={expandedSteps.includes(result.step_order)}
        inputExpanded={expandedInputSteps.includes(result.step_order)}
        panelId={getStepPanelId(result.step_order)}
        {runId}
        isPowerUser={$mode === "power_user"}
        {intric}
        onToggle={toggleStep}
        onToggleInput={toggleInputExpand}
        onCopyPayload={copyPayload}
        onDownloadArtifact={downloadArtifact}
        {getStatusColor}
        {getStatusDotColor}
        {getStatusLabel}
        {getRuntimeInputSummaryLabel}
        {formatElapsedMs}
        {formatBytes}
        {getCacheStatusLabel}
      />
    {/each}
  </div>
{/if}
