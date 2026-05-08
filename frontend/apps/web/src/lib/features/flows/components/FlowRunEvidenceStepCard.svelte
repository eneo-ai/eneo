<script lang="ts">
  import type { FlowRunResultFile, FlowRunStep, Intric } from "@intric/intric-js";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconCopy } from "@intric/icons/copy";
  import { IconCheck } from "@intric/icons/check";
  import { Markdown } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import FlowRunKnowledgeTrace from "./FlowRunKnowledgeTrace.svelte";
  import FlowJsonViewer from "./FlowJsonViewer.svelte";
  import FlowRunResultFileButton from "./FlowRunResultFileButton.svelte";
  import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";
  import type {
    RuntimeInputSummary,
    TemplateProvenanceSummary
  } from "$lib/features/flows/flowEvidenceProvenance";

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

  let {
    result,
    resultFiles = [],
    stepDef,
    duration,
    transcription,
    runtimeInput,
    templateProvenance,
    stepRag,
    stepAttempts,
    copiedKey,
    expanded,
    panelId,
    isPowerUser,
    intric,
    onToggle,
    onCopyPayload,
    onDownloadArtifact,
    getRuntimeInputSummaryLabel,
    formatElapsedMs,
    formatBytes,
    getCacheStatusLabel
  }: {
    result: FlowRunStep;
    resultFiles?: FlowRunResultFile[];
    stepDef: Record<string, unknown> | undefined;
    duration: string | null;
    transcription: FlowRunTranscriptionTelemetry | null;
    runtimeInput: RuntimeInputSummary | null;
    templateProvenance: TemplateProvenanceSummary | null;
    stepRag: Record<string, unknown> | null;
    stepAttempts: Record<string, unknown>[];
    copiedKey: string | null;
    expanded: boolean;
    panelId: string;
    isPowerUser: boolean;
    intric: Intric;
    onToggle: (stepOrder: number) => void;
    onCopyPayload: (key: string, payload: unknown, failureMessage: string) => Promise<void>;
    onDownloadArtifact: (fileId: string) => Promise<void>;
    getRuntimeInputSummaryLabel: (fileCount: number) => string;
    formatElapsedMs: (value: number | undefined) => string;
    formatBytes: (value: number | undefined) => string;
    getCacheStatusLabel: (
      usedCache: boolean | undefined,
      cachedFilesCount: number | undefined,
      filesCount: number | undefined
    ) => string;
  } = $props();

  let inputOpen = $state(false);
  const hasResultFiles = $derived(resultFiles.length > 0);
</script>

<Card.Root class="overflow-hidden">
  <button
    class="hover:bg-hover-dimmer flex w-full items-center justify-between px-5 py-3.5 text-left"
    aria-expanded={expanded}
    aria-controls={panelId}
    onclick={() => onToggle(result.step_order)}
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
      <FlowRunStatusBadge status={result.status} size="xs" />
      {#if duration}
        <span class="text-secondary text-xs tabular-nums">{duration}</span>
      {/if}
    </div>
    <span class="transition-transform" class:rotate-180={expanded}>
      <IconChevronDown class="size-4" />
    </span>
  </button>

  {#if expanded}
    <div id={panelId}>
      <Card.Content class="border-default flex min-w-0 flex-col gap-4 border-t px-5 py-4">
        {#if result.effective_prompt}
          <div>
            <div class="flex items-center justify-between">
              <h4 class="text-muted text-xs font-semibold">{m.flow_run_effective_prompt()}</h4>
              <button
                class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                aria-label={m.copy()}
                onclick={() =>
                  void onCopyPayload(
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

        {#if result.output_payload_json}
          <div>
            <div class="flex items-center justify-between">
              <h4 class="text-muted text-xs font-semibold">{m.flow_run_output()}</h4>
              <button
                class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                aria-label={m.copy()}
                onclick={() =>
                  void onCopyPayload(
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
                <Badge class="bg-accent-dimmer text-accent-stronger mb-1">JSON</Badge>
                <FlowJsonViewer value={result.output_payload_json.structured} className="mt-0" />
              </div>
            {/if}

            {#if hasResultFiles}
              <div class="mt-2">
                <h4 class="text-muted text-xs font-semibold">{m.flow_run_files()}</h4>
                <div class="mt-1.5 flex flex-wrap gap-2">
                  {#each resultFiles as artifact (artifact.file_id)}
                    <FlowRunResultFileButton file={artifact} onDownload={onDownloadArtifact} />
                  {/each}
                </div>
              </div>
            {/if}

            {#if result.output_payload_json.text && !result.output_payload_json.structured && !hasResultFiles}
              <div class="bg-hover-dimmer mt-1 max-h-96 overflow-auto rounded-lg p-4">
                <Markdown source={result.output_payload_json.text} class="text-sm" />
              </div>
            {:else if !result.output_payload_json.structured && !hasResultFiles}
              <FlowJsonViewer value={result.output_payload_json} />
            {/if}
          </div>
        {/if}

        {#if result.input_payload_json}
          <Collapsible.Root bind:open={inputOpen}>
            <div class="flex items-center justify-between">
              <Collapsible.Trigger
                class="text-muted hover:text-secondary focus-visible:ring-accent-default -ml-1 flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-semibold transition-colors focus-visible:ring-2 focus-visible:outline-none"
                aria-expanded={inputOpen}
                aria-controls="step-{result.step_order}-input-panel"
              >
                <IconChevronDown
                  class="size-3 transition-transform duration-200 {inputOpen ? 'rotate-180' : ''}"
                  aria-hidden="true"
                />
                {inputOpen ? m.flow_run_hide_input() : m.flow_run_show_input()}
              </Collapsible.Trigger>
              <button
                class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                aria-label={m.flow_run_copy_input()}
                onclick={() =>
                  void onCopyPayload(
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
            <Collapsible.Content>
              <div id="step-{result.step_order}-input-panel">
                <FlowJsonViewer value={result.input_payload_json} />
              </div>
            </Collapsible.Content>
          </Collapsible.Root>
        {/if}

        {#if runtimeInput}
          <Card.Root size="sm" class="bg-hover-dimmer">
            <Card.Content class="p-3">
              <h4 class="text-muted text-xs font-semibold">{m.flow_run_runtime_input_label()}</h4>
              <div class="text-secondary mt-2 flex flex-wrap gap-2 text-[11px]">
                <Badge variant="outline">
                  {getRuntimeInputSummaryLabel(runtimeInput.fileCount)}
                </Badge>
                {#if runtimeInput.inputFormat}
                  <Badge variant="outline">
                    Format: {runtimeInput.inputFormat}
                  </Badge>
                {/if}
                {#if runtimeInput.extractedTextLength != null}
                  <Badge variant="outline">
                    Extraherad text: {runtimeInput.extractedTextLength} tecken
                  </Badge>
                {/if}
              </div>
            </Card.Content>
          </Card.Root>
        {/if}

        {#if transcription}
          <Card.Root size="sm" class="bg-hover-dimmer">
            <Card.Content class="p-3">
              <h4 class="text-muted text-xs font-semibold">{m.flow_run_transcription_label()}</h4>
              <div class="text-secondary mt-2 flex flex-wrap gap-2 text-[11px]">
                <Badge variant="outline">
                  {m.flow_run_transcription_model({ model: transcription.model ?? "\u2014" })}
                </Badge>
                <Badge variant="outline">
                  {m.flow_run_transcription_language({
                    language: transcription.language ?? "\u2014"
                  })}
                </Badge>
                <Badge variant="outline">
                  {m.flow_run_transcription_files({
                    count: String(transcription.files_count ?? 0)
                  })}
                </Badge>
                <Badge variant="outline">
                  {m.flow_run_transcription_duration({
                    duration: formatElapsedMs(transcription.elapsed_ms)
                  })}
                </Badge>
                <Badge variant="outline">
                  {m.flow_run_transcription_size({
                    size: formatBytes(transcription.transcript_bytes)
                  })}
                </Badge>
                <Badge variant="outline">
                  {m.flow_run_transcription_estimated_tokens({
                    tokens: String(transcription.estimated_tokens ?? 0)
                  })}
                </Badge>
                <Badge variant="outline">
                  {m.flow_run_transcription_cache({
                    status: getCacheStatusLabel(
                      transcription.used_cache,
                      transcription.cached_files_count,
                      transcription.files_count
                    )
                  })}
                </Badge>
              </div>
            </Card.Content>
          </Card.Root>
        {/if}

        {#if stepRag}
          <FlowRunKnowledgeTrace rag={stepRag} stepOrder={result.step_order} {intric} />
        {/if}

        {#if templateProvenance}
          <Card.Root size="sm" class="bg-hover-dimmer">
            <Card.Content class="p-3">
              <h4 class="text-muted text-xs font-semibold">
                {m.flow_run_template_provenance_label()}
              </h4>
              <div class="text-secondary mt-2 flex flex-col gap-2 text-[11px]">
                <div class="flex flex-wrap gap-2">
                  <Badge variant="outline">
                    {templateProvenance.templateName}
                  </Badge>
                  {#if templateProvenance.publishedFlowVersion != null}
                    <Badge variant="outline">
                      v{templateProvenance.publishedFlowVersion}
                    </Badge>
                  {/if}
                </div>
                <div class="flex flex-wrap gap-2">
                  {#if templateProvenance.templateAssetId}
                    <Badge variant="outline">
                      Asset: {templateProvenance.templateAssetId}
                    </Badge>
                  {/if}
                  {#if templateProvenance.templateFileId}
                    <Badge variant="outline">
                      Fil: {templateProvenance.templateFileId}
                    </Badge>
                  {/if}
                  {#if templateProvenance.checksum}
                    <Badge variant="outline">
                      {templateProvenance.checksum}
                    </Badge>
                  {/if}
                </div>
              </div>
            </Card.Content>
          </Card.Root>
        {/if}

        {#if isPowerUser && stepAttempts.length > 0}
          <div>
            <div class="flex items-center justify-between">
              <h4 class="text-muted text-xs font-semibold">{m.flow_run_attempts()}</h4>
              <button
                class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                aria-label={m.copy()}
                onclick={() =>
                  void onCopyPayload(
                    `step-${result.step_order}-attempts`,
                    stepAttempts,
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
            <FlowJsonViewer value={stepAttempts} maxHeightClass="max-h-[300px]" />
          </div>
        {/if}

        {#if result.num_tokens_input != null || result.num_tokens_output != null}
          <div class="border-default text-muted flex items-center gap-2 border-t pt-3 text-xs">
            <span class="tabular-nums">{m.flow_run_tokens()}</span>
            <span class="text-dimmer">&middot;</span>
            <span class="tabular-nums"
              >{m.flow_run_tokens_in({ count: String(result.num_tokens_input ?? 0) })}</span
            >
            <span class="text-dimmer">&middot;</span>
            <span class="tabular-nums"
              >{m.flow_run_tokens_out({ count: String(result.num_tokens_output ?? 0) })}</span
            >
          </div>
        {/if}

        {#if result.error_message}
          <Alert.Root variant="destructive">
            <Alert.Title class="text-xs font-semibold">{m.flow_run_error()}</Alert.Title>
            <Alert.Description>
              <pre
                class="mt-1 max-h-60 overflow-auto font-mono text-xs break-words whitespace-pre-wrap">{result.error_message}</pre>
            </Alert.Description>
          </Alert.Root>
        {/if}
      </Card.Content>
    </div>
  {/if}
</Card.Root>
