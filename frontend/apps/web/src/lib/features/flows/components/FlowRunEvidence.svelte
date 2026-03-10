<svelte:options runes={false} />

<script lang="ts">
  import type { FlowRunDebugExport, Intric, FlowStepResult } from "@intric/intric-js";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconCopy } from "@intric/icons/copy";
  import { IconCheck } from "@intric/icons/check";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconArrowDownToLine } from "@intric/icons/arrow-down-to-line";
  import { Button, Markdown } from "@intric/ui";
  import { highlightJson } from "./highlightJson";
  import { onDestroy, onMount } from "svelte";
  import { slide } from "svelte/transition";
  import { toast } from "$lib/components/toast";
  import {
    downloadJsonArtifact as triggerJsonDownload,
    serializeEvidencePayload
  } from "./flowRunEvidenceActions";
  import { getFlowRunStatusLabel } from "./flowRunStatusLabel";
  import { m } from "$lib/paraglide/messages";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import FlowRunKnowledgeTraceComponent from "./FlowRunKnowledgeTrace.svelte";
  import {
    getRuntimeInputSummary,
    getTemplateProvenanceSummary
  } from "$lib/features/flows/flowEvidenceProvenance";

  export let runId: string;
  export let flowId: string;
  export let intric: Intric;
  export let runStatus: string;

  let evidence: {
    run: Record<string, unknown>;
    definition_snapshot: Record<string, unknown>;
    step_results: FlowStepResult[];
    step_attempts: Record<string, unknown>[];
    debug_export: FlowRunDebugExport;
  } | null = null;
  let loading = true;
  let loadError = false;
  let expandedSteps: number[] = [];
  let hasAutoExpanded = false;
  let copiedKey: string | null = null;
  let copiedTimer: ReturnType<typeof setTimeout> | null = null;
  const mode = getFlowUserMode();
  let stepAttemptsByOrder: Record<number, Record<string, unknown>[]> = {};
  const FlowRunKnowledgeTrace = FlowRunKnowledgeTraceComponent as any;
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

  onMount(async () => {
    try {
      evidence = await intric.flows.runs.evidence({ id: runId, flowId });
    } catch (e) {
      console.error("Error loading evidence", e);
      loadError = true;
    }
    loading = false;
  });

  let lastFetchedStatus: string | null = null;

  $: if (
    runStatus &&
    evidence &&
    lastFetchedStatus !== runStatus &&
    (runStatus === "completed" || runStatus === "failed" || runStatus === "cancelled")
  ) {
    lastFetchedStatus = runStatus;
    void refetchEvidence();
  }

  $: if (evidence && evidence.step_results.length > 0 && !hasAutoExpanded) {
    hasAutoExpanded = true;
    expandedSteps = [evidence.step_results[0].step_order];
  }

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
    const hasOrder = expandedSteps.includes(order);
    if (hasOrder) {
      expandedSteps = expandedSteps.filter((item) => item !== order);
    } else {
      expandedSteps = [...expandedSteps, order];
    }
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

  function getStepAttempts(stepOrder: number): Record<string, unknown>[] {
    return stepAttemptsByOrder[stepOrder] ?? [];
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

  $: stepAttemptsByOrder = (() => {
    const grouped: Record<number, Record<string, unknown>[]> = {};
    for (const attempt of evidence?.step_attempts ?? []) {
      const stepOrder = Number((attempt as { step_order?: unknown }).step_order ?? 0);
      grouped[stepOrder] ??= [];
      grouped[stepOrder].push(attempt);
    }
    return grouped;
  })();

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
  <p class="text-negative-default text-sm">{m.flow_run_evidence_error()}</p>
{:else}
  <div class="flex flex-col gap-2">
    {#if $mode === "power_user"}
      <div class="flex justify-end">
        <div class="flex flex-wrap gap-2">
          {#if evidence.debug_export}
            {@const debugExport = evidence.debug_export}
            <Button
              variant="outlined"
              size="small"
              on:click={() =>
                copyPayload("debug-export", debugExport, m.flow_run_copy_debug_export_failed())}
            >
              {copiedKey === "debug-export" ? m.copied() : m.flow_run_copy_debug_export()}
            </Button>
            <Button
              variant="outlined"
              size="small"
              on:click={() =>
                downloadJsonArtifact(
                  `flow-debug-export-${runId}.json`,
                  debugExport,
                  m.flow_run_download_debug_export_failed()
                )}
            >
              {m.flow_run_download_debug_export()}
            </Button>
          {/if}
          <Button
            variant="outlined"
            size="small"
            on:click={() => copyPayload("full-evidence", evidence, m.flow_run_copy_failed())}
          >
            {copiedKey === "full-evidence" ? m.copied() : `${m.copy()} JSON`}
          </Button>
        </div>
      </div>
    {/if}

    {#each evidence.step_results as result (result.id ?? result.step_order)}
      {@const stepDef = ((evidence.definition_snapshot?.steps ?? []) as any[]).find(
        (s) => s.step_order === result.step_order
      )}
      {@const duration = getStepDuration(result.step_order)}
      {@const transcription = getStepTranscription(result)}
      {@const runtimeInput = getRuntimeInputSummary(result.input_payload_json)}
      {@const templateProvenance = getTemplateProvenanceSummary(result.output_payload_json)}
      {@const stepRag = getStepRag(result.step_order)}
      <div
        class="bg-primary border-default overflow-hidden rounded-lg border shadow-sm transition-shadow hover:shadow-md"
      >
        <button
          class="hover:bg-hover-dimmer flex w-full items-center justify-between px-5 py-3.5 text-left"
          aria-expanded={expandedSteps.includes(result.step_order)}
          aria-controls={getStepPanelId(result.step_order)}
          on:click={() => toggleStep(result.step_order)}
        >
          <div class="flex items-center gap-2.5">
            <span
              class="bg-hover-dimmer flex size-6 items-center justify-center rounded-full text-xs font-semibold"
            >
              {result.step_order}
            </span>
            <span class="text-sm font-medium">
              {stepDef?.user_description ??
                m.flow_step_fallback_label({ order: String(result.step_order) })}
            </span>
            <span
              class="{getStatusColor(
                result.status
              )} inline-flex items-center gap-1.5 text-[11px] font-medium"
            >
              <span class="{getStatusDotColor(result.status)} size-1.5 shrink-0 rounded-full"
              ></span>
              {getStatusLabel(result.status)}
            </span>
            {#if duration}
              <span class="text-secondary text-xs tabular-nums">{duration}</span>
            {/if}
          </div>
          <span
            class="transition-transform"
            class:rotate-180={expandedSteps.includes(result.step_order)}
          >
            <IconChevronDown class="size-4" />
          </span>
        </button>

        {#if expandedSteps.includes(result.step_order)}
          <div id={getStepPanelId(result.step_order)} transition:slide={{ duration: 200 }}>
            <div class="border-default flex min-w-0 flex-col gap-4 border-t px-5 py-4">
              {#if result.effective_prompt}
                <div>
                  <div class="flex items-center justify-between">
                    <h4 class="text-muted text-xs font-semibold">
                      {m.flow_run_effective_prompt()}
                    </h4>
                    <button
                      class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                      aria-label={m.copy()}
                      on:click={() =>
                        copyPayload(
                          `step-${result.step_order}-prompt`,
                          result.effective_prompt,
                          m.flow_run_copy_failed()
                        )}
                    >
                      {#if copiedKey === `step-${result.step_order}-prompt`}
                        <IconCheck class="text-positive-default size-3.5" />
                      {:else}
                        <IconCopy class="size-3.5" />
                      {/if}
                    </button>
                  </div>
                  <pre
                    class="bg-hover-dimmer mt-1.5 max-h-80 overflow-auto rounded-lg p-3 text-sm leading-relaxed break-words whitespace-pre-wrap">{result.effective_prompt}</pre>
                </div>
              {/if}

              {#if result.input_payload_json}
                <div>
                  <div class="flex items-center justify-between">
                    <h4 class="text-muted text-xs font-semibold">{m.flow_run_input()}</h4>
                    <button
                      class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                      aria-label={m.copy()}
                      on:click={() =>
                        copyPayload(
                          `step-${result.step_order}-input`,
                          result.input_payload_json,
                          m.flow_run_copy_failed()
                        )}
                    >
                      {#if copiedKey === `step-${result.step_order}-input`}
                        <IconCheck class="text-positive-default size-3.5" />
                      {:else}
                        <IconCopy class="size-3.5" />
                      {/if}
                    </button>
                  </div>
                  <pre
                    class="json-hl bg-hover-dimmer mt-1 max-h-80 overflow-auto rounded-lg p-3 font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap">{@html highlightJson(
                      JSON.stringify(result.input_payload_json, null, 2)
                    )}</pre>
                </div>
              {/if}

              {#if runtimeInput}
                <div class="border-default bg-hover-dimmer rounded-lg border p-3">
                  <h4 class="text-muted text-xs font-semibold">Körningsindata</h4>
                  <div class="text-secondary mt-2 flex flex-wrap gap-2 text-[11px]">
                    <span class="border-default bg-primary rounded-md border px-2 py-1">
                      {getRuntimeInputSummaryLabel(runtimeInput.fileCount)}
                    </span>
                    {#if runtimeInput.inputFormat}
                      <span class="border-default bg-primary rounded-md border px-2 py-1">
                        Format: {runtimeInput.inputFormat}
                      </span>
                    {/if}
                    {#if runtimeInput.extractedTextLength != null}
                      <span class="border-default bg-primary rounded-md border px-2 py-1">
                        Extraherad text: {runtimeInput.extractedTextLength} tecken
                      </span>
                    {/if}
                  </div>
                </div>
              {/if}

              {#if transcription}
                <div class="border-default bg-hover-dimmer rounded-lg border p-3">
                  <h4 class="text-muted text-xs font-semibold">
                    {m.flow_run_transcription_label()}
                  </h4>
                  <div class="text-secondary mt-2 flex flex-wrap gap-2 text-[11px]">
                    <span class="border-default bg-primary rounded-md border px-2 py-1">
                      {m.flow_run_transcription_model({ model: transcription.model ?? "—" })}
                    </span>
                    <span class="border-default bg-primary rounded-md border px-2 py-1">
                      {m.flow_run_transcription_language({
                        language: transcription.language ?? "—"
                      })}
                    </span>
                    <span class="border-default bg-primary rounded-md border px-2 py-1">
                      {m.flow_run_transcription_files({
                        count: String(transcription.files_count ?? 0)
                      })}
                    </span>
                    <span class="border-default bg-primary rounded-md border px-2 py-1">
                      {m.flow_run_transcription_duration({
                        duration: formatElapsedMs(transcription.elapsed_ms)
                      })}
                    </span>
                    <span class="border-default bg-primary rounded-md border px-2 py-1">
                      {m.flow_run_transcription_size({
                        size: formatBytes(transcription.transcript_bytes)
                      })}
                    </span>
                    <span class="border-default bg-primary rounded-md border px-2 py-1">
                      {m.flow_run_transcription_estimated_tokens({
                        tokens: String(transcription.estimated_tokens ?? 0)
                      })}
                    </span>
                    <span class="border-default bg-primary rounded-md border px-2 py-1">
                      {m.flow_run_transcription_cache({
                        status: getCacheStatusLabel(
                          transcription.used_cache,
                          transcription.cached_files_count,
                          transcription.files_count
                        )
                      })}
                    </span>
                  </div>
                </div>
              {/if}

              {#if stepRag}
                <FlowRunKnowledgeTrace rag={stepRag} stepOrder={result.step_order} {intric} />
              {/if}

              {#if result.output_payload_json}
                <div>
                  <div class="flex items-center justify-between">
                    <h4 class="text-muted text-xs font-semibold">{m.flow_run_output()}</h4>
                    <button
                      class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                      aria-label={m.copy()}
                      on:click={() =>
                        copyPayload(
                          `step-${result.step_order}-output`,
                          result.output_payload_json,
                          m.flow_run_copy_failed()
                        )}
                    >
                      {#if copiedKey === `step-${result.step_order}-output`}
                        <IconCheck class="text-positive-default size-3.5" />
                      {:else}
                        <IconCopy class="size-3.5" />
                      {/if}
                    </button>
                  </div>

                  {#if result.output_payload_json.structured}
                    <div class="mt-1">
                      <span
                        class="bg-accent-dimmer text-accent-stronger mb-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                        >JSON</span
                      >
                      <pre
                        class="json-hl border-accent-default bg-hover-dimmer max-h-80 overflow-auto rounded-lg border-l-2 p-3 font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap">{@html highlightJson(
                          JSON.stringify(result.output_payload_json.structured, null, 2)
                        )}</pre>
                    </div>
                  {/if}

                  {#if result.output_payload_json.artifacts?.length}
                    <div class="mt-2">
                      <h4 class="text-muted text-xs font-semibold">{m.flow_run_files()}</h4>
                      <div class="mt-1.5 flex flex-wrap gap-2">
                        {#each result.output_payload_json.artifacts as artifact (artifact.file_id)}
                          {@const ext = artifact.name?.includes(".")
                            ? artifact.name.split(".").pop()?.toLowerCase()
                            : ""}
                          <button
                            class="group border-default bg-primary inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium shadow-sm transition-all hover:-translate-y-px hover:shadow-md"
                            on:click={() => downloadArtifact(artifact.file_id)}
                          >
                            <IconArrowDownToLine
                              class="text-muted group-hover:text-secondary size-4"
                            />
                            <span>{artifact.name}</span>
                            {#if ext}
                              <span
                                class="bg-accent-dimmer text-accent-stronger rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                                >{ext}</span
                              >
                            {/if}
                          </button>
                        {/each}
                      </div>
                    </div>
                  {/if}

                  {#if result.output_payload_json.text && !result.output_payload_json.structured}
                    <div class="bg-hover-dimmer mt-1 max-h-96 overflow-auto rounded-lg p-4">
                      <Markdown source={result.output_payload_json.text} class="text-sm" />
                    </div>
                  {:else if !result.output_payload_json.structured && !result.output_payload_json.artifacts?.length}
                    <pre
                      class="json-hl border-accent-default bg-hover-dimmer mt-1 max-h-80 overflow-auto rounded-lg border-l-2 p-3 font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap">{@html highlightJson(
                        JSON.stringify(result.output_payload_json, null, 2)
                      )}</pre>
                  {/if}
                </div>
              {/if}

              {#if templateProvenance}
                <div class="border-default bg-hover-dimmer rounded-lg border p-3">
                  <h4 class="text-muted text-xs font-semibold">Mallproveniens</h4>
                  <div class="text-secondary mt-2 flex flex-col gap-2 text-[11px]">
                    <div class="flex flex-wrap gap-2">
                      <span class="border-default bg-primary rounded-md border px-2 py-1">
                        {templateProvenance.templateName}
                      </span>
                      {#if templateProvenance.publishedFlowVersion != null}
                        <span class="border-default bg-primary rounded-md border px-2 py-1">
                          v{templateProvenance.publishedFlowVersion}
                        </span>
                      {/if}
                    </div>
                    <div class="flex flex-wrap gap-2">
                      {#if templateProvenance.templateAssetId}
                        <span class="border-default bg-primary rounded-md border px-2 py-1">
                          Asset: {templateProvenance.templateAssetId}
                        </span>
                      {/if}
                      {#if templateProvenance.templateFileId}
                        <span class="border-default bg-primary rounded-md border px-2 py-1">
                          Fil: {templateProvenance.templateFileId}
                        </span>
                      {/if}
                      {#if templateProvenance.checksum}
                        <span class="border-default bg-primary rounded-md border px-2 py-1">
                          {templateProvenance.checksum}
                        </span>
                      {/if}
                    </div>
                  </div>
                </div>
              {/if}

              {#if $mode === "power_user" && getStepAttempts(result.step_order).length > 0}
                <div>
                  <div class="flex items-center justify-between">
                    <h4 class="text-muted text-xs font-semibold">{m.flow_run_attempts()}</h4>
                    <button
                      class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                      aria-label={m.copy()}
                      on:click={() =>
                        copyPayload(
                          `step-${result.step_order}-attempts`,
                          getStepAttempts(result.step_order),
                          m.flow_run_copy_failed()
                        )}
                    >
                      {#if copiedKey === `step-${result.step_order}-attempts`}
                        <IconCheck class="text-positive-default size-3.5" />
                      {:else}
                        <IconCopy class="size-3.5" />
                      {/if}
                    </button>
                  </div>
                  <pre
                    class="json-hl border-accent-default bg-hover-dimmer mt-1 max-h-80 overflow-auto rounded-lg border-l-2 p-3 font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap">{@html highlightJson(
                      JSON.stringify(getStepAttempts(result.step_order), null, 2)
                    )}</pre>
                </div>
              {/if}

              {#if result.num_tokens_input != null || result.num_tokens_output != null}
                <div
                  class="border-default text-muted flex items-center gap-2 border-t pt-3 text-xs"
                >
                  <span class="tabular-nums">{m.flow_run_tokens()}</span>
                  <span class="text-dimmer">&middot;</span>
                  <span class="tabular-nums">{result.num_tokens_input ?? 0} in</span>
                  <span class="text-dimmer">&middot;</span>
                  <span class="tabular-nums">{result.num_tokens_output ?? 0} out</span>
                </div>
              {/if}

              {#if result.error_message}
                <div>
                  <h4 class="text-negative-stronger text-xs font-semibold">{m.flow_run_error()}</h4>
                  <pre
                    class="bg-negative-dimmer text-negative-stronger mt-1 max-h-60 overflow-auto rounded-md p-3 font-mono text-xs break-words whitespace-pre-wrap">{result.error_message}</pre>
                </div>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  .json-hl :global(.json-key) {
    color: var(--accent-stronger);
  }
  .json-hl :global(.json-string) {
    color: var(--positive-stronger);
  }
  .json-hl :global(.json-number) {
    color: var(--warning-stronger);
  }
  .json-hl :global(.json-boolean) {
    color: var(--beta-indicator);
  }
</style>
