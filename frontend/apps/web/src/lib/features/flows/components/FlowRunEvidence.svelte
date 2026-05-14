<script lang="ts">
  import type {
    FlowRunEvidenceWithTypedSteps,
    FlowRunResultFile,
    FlowRunStep,
    Intric
  } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { onMount } from "svelte";
  import { toast } from "$lib/components/toast";
  import {
    downloadEvidenceExport,
    downloadJsonArtifact as triggerJsonDownload,
    serializeEvidencePayload
  } from "./flowRunEvidenceActions";
  import { m } from "$lib/paraglide/messages";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import {
    getRuntimeInputSummary,
    getTemplateProvenanceSummary
  } from "$lib/features/flows/flowEvidenceProvenance";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import FlowRunProgressView from "./FlowRunProgressView.svelte";
  import FlowRunEvidenceToolbar from "./FlowRunEvidenceToolbar.svelte";
  import FlowRunEvidenceSummary from "./FlowRunEvidenceSummary.svelte";
  import FlowRunEvidenceStepCard from "./FlowRunEvidenceStepCard.svelte";
  import type { FlowRunProgressSnapshot } from "./flowRunProgress";
  import { getReviewPolicyErrorStepsFromDefinitionSnapshot } from "$lib/features/flows/flowRuntimeErrorMapping";

  let {
    runId,
    flowId,
    sensitiveCareDataFlow = false,
    eneo,
    runStatus,
    fallbackSnapshot = null
  }: {
    runId: string;
    flowId: string;
    sensitiveCareDataFlow?: boolean;
    eneo: Intric;
    runStatus: string;
    fallbackSnapshot?: FlowRunProgressSnapshot | null;
  } = $props();

  type EvidencePayload = FlowRunEvidenceWithTypedSteps;

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

  let evidence: EvidencePayload | null = $state(null);
  let loading = $state(true);
  let loadError = $state(false);
  let expandedSteps: number[] = $state([]);
  let hasAutoExpanded = $state(false);
  let copiedKey: string | null = $state(null);
  let copiedTimer: ReturnType<typeof setTimeout> | null = $state(null);
  const mode = getFlowUserMode();
  let stepAttemptsByOrder: Record<number, Record<string, unknown>[]> = $derived.by(() =>
    groupStepAttemptsByOrder(evidence?.step_attempts ?? [])
  );
  let resultFilesByStepResultId: Record<string, FlowRunResultFile[]> = $derived.by(() =>
    groupResultFilesByStepResultId(evidence?.result_files ?? [])
  );
  let resultFilesByStepOrder: Record<number, FlowRunResultFile[]> = $derived.by(() =>
    groupResultFilesByStepOrder(evidence?.result_files ?? [])
  );
  let reviewPolicyDefinitionSteps = $derived.by(() => {
    const definitionSteps = evidence?.definition_snapshot?.steps;
    return getReviewPolicyErrorStepsFromDefinitionSnapshot(
      Array.isArray(definitionSteps) ? definitionSteps : []
    );
  });

  onMount(async () => {
    try {
      evidence = await eneo.flows.runs.evidence({ id: runId, flowId });
    } catch (e) {
      console.error("Error loading evidence", e);
      loadError = true;
    }
    loading = false;
  });

  $effect(() => {
    if (evidence && evidence.step_results.length > 0 && !hasAutoExpanded) {
      hasAutoExpanded = true;
      expandedSteps = [evidence.step_results[0].step_order];
    }
  });

  $effect(() => {
    return () => {
      if (copiedTimer) clearTimeout(copiedTimer);
    };
  });

  function toggleStep(order: number) {
    expandedSteps = expandedSteps.includes(order)
      ? expandedSteps.filter((item) => item !== order)
      : [...expandedSteps, order];
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
      await downloadEvidenceExport({ intric: eneo, flowId, runId });
    } catch (error) {
      console.error("Could not download canonical evidence export", error);
      toast.error(m.flow_run_download_evidence_export_failed());
    }
  }

  function getStepAttempts(stepOrder: number): Record<string, unknown>[] {
    return stepAttemptsByOrder[stepOrder] ?? [];
  }

  function getStepResultFiles(result: FlowRunStep): FlowRunResultFile[] {
    if (result.id && resultFilesByStepResultId[result.id]) {
      return resultFilesByStepResultId[result.id];
    }
    return resultFilesByStepOrder[result.step_order] ?? [];
  }

  function groupStepAttemptsByOrder(
    attempts: Record<string, unknown>[]
  ): Record<number, Record<string, unknown>[]> {
    const grouped: Record<number, Record<string, unknown>[]> = {};
    for (const attempt of attempts) {
      const stepOrder = Number((attempt as { step_order?: unknown }).step_order ?? 0);
      grouped[stepOrder] ??= [];
      grouped[stepOrder].push(attempt);
    }
    return grouped;
  }

  function groupResultFilesByStepResultId(
    resultFiles: FlowRunResultFile[]
  ): Record<string, FlowRunResultFile[]> {
    const grouped: Record<string, FlowRunResultFile[]> = {};
    for (const resultFile of resultFiles) {
      grouped[resultFile.step_result_id] ??= [];
      grouped[resultFile.step_result_id].push(resultFile);
    }
    return grouped;
  }

  function groupResultFilesByStepOrder(
    resultFiles: FlowRunResultFile[]
  ): Record<number, FlowRunResultFile[]> {
    const grouped: Record<number, FlowRunResultFile[]> = {};
    for (const resultFile of resultFiles) {
      grouped[resultFile.step_order] ??= [];
      grouped[resultFile.step_order].push(resultFile);
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
      const { url } = await eneo.flows.runs.artifactSignedUrl({
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

  function getStepTranscription(result: FlowRunStep): FlowRunTranscriptionTelemetry | null {
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
    if (value === undefined) return "\u2014";
    if (value < 1000) return `${value}ms`;
    return `${(value / 1000).toFixed(1)}s`;
  }

  function formatBytes(value: number | undefined): string {
    if (value === undefined) return "\u2014";
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
    return fileCount === 1
      ? m.flow_run_uploaded_files_singular()
      : m.flow_run_uploaded_files_plural({ count: String(fileCount) });
  }
</script>

{#if loading}
  {#if fallbackSnapshot}
    <FlowRunProgressView snapshot={fallbackSnapshot} loadingTerminalDetails />
  {:else}
    <div class="text-muted flex items-center justify-center gap-2 py-6 text-sm" aria-busy="true">
      <IconLoadingSpinner class="size-4 animate-spin" />
      {m.flow_run_evidence_loading()}
    </div>
  {/if}
{:else if loadError || evidence === null}
  <Alert.Root variant="destructive">
    <Alert.Description>{m.flow_run_evidence_error()}</Alert.Description>
  </Alert.Root>
{:else}
  <div class="flex flex-col gap-4">
    {#if $mode === "power_user"}
      <!-- Power-user toolbar already includes status + trace + redaction badges, so the
           summary card is only rendered for Enkel mode to avoid duplication. -->
      <FlowRunEvidenceToolbar
        debugExport={evidence.debug_export}
        {evidence}
        {copiedKey}
        {sensitiveCareDataFlow}
        {runStatus}
        traceId={evidence.debug_export?.run?.trace_id ?? null}
        onDownloadCanonicalEvidence={downloadCanonicalEvidenceExport}
        onCopyPayload={copyPayload}
        onDownloadJsonArtifact={downloadJsonArtifact}
      />
    {:else}
      <FlowRunEvidenceSummary
        {runStatus}
        traceId={evidence.debug_export?.run?.trace_id ?? null}
        redactionApplied={evidence.debug_export?.security?.redaction_applied === true}
      />
    {/if}

    {#each evidence.step_results as result (result.id ?? result.step_order)}
      {@const stepDef = (
        (evidence.definition_snapshot?.steps ?? []) as Record<string, unknown>[]
      ).find((step) => step.step_order === result.step_order)}
      <FlowRunEvidenceStepCard
        {result}
        resultFiles={getStepResultFiles(result)}
        {stepDef}
        duration={getStepDuration(result.step_order)}
        transcription={getStepTranscription(result)}
        runtimeInput={getRuntimeInputSummary(result.input_payload_json)}
        templateProvenance={getTemplateProvenanceSummary(result.output_payload_json)}
        stepRag={getStepRag(result.step_order)}
        stepAttempts={getStepAttempts(result.step_order)}
        {reviewPolicyDefinitionSteps}
        {copiedKey}
        expanded={expandedSteps.includes(result.step_order)}
        panelId={getStepPanelId(result.step_order)}
        isPowerUser={$mode === "power_user"}
        intric={eneo}
        onToggle={toggleStep}
        onCopyPayload={copyPayload}
        onDownloadArtifact={downloadArtifact}
        {getRuntimeInputSummaryLabel}
        {formatElapsedMs}
        {formatBytes}
        {getCacheStatusLabel}
      />
    {/each}
  </div>
{/if}
