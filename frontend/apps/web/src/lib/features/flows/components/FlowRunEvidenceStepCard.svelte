<svelte:options runes={false} />

<script lang="ts">
  import type { FlowStepResult, Intric } from "@intric/intric-js";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconCopy } from "@intric/icons/copy";
  import { IconCheck } from "@intric/icons/check";
  import { IconArrowDownToLine } from "@intric/icons/arrow-down-to-line";
  import { Markdown } from "@intric/ui";
  import { slide } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
  import FlowRunKnowledgeTrace from "./FlowRunKnowledgeTrace.svelte";
  import type {
    RuntimeInputSummary,
    TemplateProvenanceSummary
  } from "$lib/features/flows/flowEvidenceProvenance";

  export let result: FlowStepResult;
  export let stepDef: Record<string, unknown> | undefined;
  export let duration: string | null;
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

  export let transcription: FlowRunTranscriptionTelemetry | null;
  export let runtimeInput: RuntimeInputSummary | null;
  export let templateProvenance: TemplateProvenanceSummary | null;
  export let stepRag: Record<string, unknown> | null;
  export let stepAttempts: Record<string, unknown>[];
  export let copiedKey: string | null;
  export let expanded: boolean;
  export let inputExpanded: boolean;
  export let panelId: string;
  export let runId: string;
  export let isPowerUser: boolean;
  export let intric: Intric;
  export let onToggle: (stepOrder: number) => void;
  export let onToggleInput: (stepOrder: number) => void;
  export let onCopyPayload: (key: string, payload: unknown, failureMessage: string) => Promise<void>;
  export let onDownloadArtifact: (fileId: string) => Promise<void>;
  export let getStatusColor: (status: string) => string;
  export let getStatusDotColor: (status: string) => string;
  export let getStatusLabel: (status: string) => string;
  export let getRuntimeInputSummaryLabel: (fileCount: number) => string;
  export let formatElapsedMs: (value: number | undefined) => string;
  export let formatBytes: (value: number | undefined) => string;
  export let getCacheStatusLabel: (
    usedCache: boolean | undefined,
    cachedFilesCount: number | undefined,
    filesCount: number | undefined
  ) => string;
</script>

<div
  class="bg-primary border-default overflow-hidden rounded-lg border shadow-sm transition-shadow hover:shadow-md"
>
  <button
    class="hover:bg-hover-dimmer flex w-full items-center justify-between px-5 py-3.5 text-left"
    aria-expanded={expanded}
    aria-controls={panelId}
    on:click={() => onToggle(result.step_order)}
  >
    <div class="flex items-center gap-2.5">
      <span
        class="bg-hover-dimmer flex size-6 items-center justify-center rounded-full text-xs font-semibold"
      >
        {result.step_order}
      </span>
      <span class="text-sm font-medium">
        {stepDef?.user_description ?? m.flow_step_fallback_label({ order: String(result.step_order) })}
      </span>
      <span
        class="{getStatusColor(result.status)} inline-flex items-center gap-1.5 text-[11px] font-medium"
      >
        <span class="{getStatusDotColor(result.status)} size-1.5 shrink-0 rounded-full"></span>
        {getStatusLabel(result.status)}
      </span>
      {#if duration}
        <span class="text-secondary text-xs tabular-nums">{duration}</span>
      {/if}
    </div>
    <span class="transition-transform" class:rotate-180={expanded}>
      <IconChevronDown class="size-4" />
    </span>
  </button>

  {#if expanded}
    <div id={panelId} transition:slide={{ duration: 200 }}>
      <div class="border-default flex min-w-0 flex-col gap-4 border-t px-5 py-4">
        {#if result.effective_prompt}
          <div>
            <div class="flex items-center justify-between">
              <h4 class="text-muted text-xs font-semibold">{m.flow_run_effective_prompt()}</h4>
              <button
                class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                aria-label={m.copy()}
                on:click={() =>
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
                on:click={() =>
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
                <span
                  class="bg-accent-dimmer text-accent-stronger mb-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                  >JSON</span
                >
                <pre
                  class="border-accent-default bg-hover-dimmer max-h-80 overflow-auto rounded-lg border-l-2 p-3 font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap">{JSON.stringify(
                    result.output_payload_json.structured,
                    null,
                    2
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
                      on:click={() => void onDownloadArtifact(artifact.file_id)}
                    >
                      <IconArrowDownToLine class="text-muted group-hover:text-secondary size-4" />
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
                class="border-accent-default bg-hover-dimmer mt-1 max-h-80 overflow-auto rounded-lg border-l-2 p-3 font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap">{JSON.stringify(
                  result.output_payload_json,
                  null,
                  2
                )}</pre>
            {/if}
          </div>
        {/if}

        {#if result.input_payload_json}
          <div>
            <div class="flex items-center justify-between">
              <button
                class="text-muted hover:text-secondary focus-visible:ring-accent-default -ml-1 flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-semibold transition-colors focus-visible:ring-2 focus-visible:outline-none"
                on:click={() => onToggleInput(result.step_order)}
                aria-expanded={inputExpanded}
                aria-controls="step-{result.step_order}-input-panel"
              >
                <IconChevronDown
                  class="size-3 transition-transform duration-200 {inputExpanded ? '' : '-rotate-90'}"
                />
                {m.flow_run_input()}
              </button>
              <button
                class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                aria-label={m.copy()}
                on:click={() =>
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
            {#if inputExpanded}
              <pre
                id="step-{result.step_order}-input-panel"
                transition:slide={{ duration: 200 }}
                class="bg-hover-dimmer mt-1 max-h-80 overflow-auto rounded-lg p-3 font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap">{JSON.stringify(
                  result.input_payload_json,
                  null,
                  2
                )}</pre>
            {/if}
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
            <h4 class="text-muted text-xs font-semibold">{m.flow_run_transcription_label()}</h4>
            <div class="text-secondary mt-2 flex flex-wrap gap-2 text-[11px]">
              <span class="border-default bg-primary rounded-md border px-2 py-1">
                {m.flow_run_transcription_model({ model: transcription.model ?? "—" })}
              </span>
              <span class="border-default bg-primary rounded-md border px-2 py-1">
                {m.flow_run_transcription_language({ language: transcription.language ?? "—" })}
              </span>
              <span class="border-default bg-primary rounded-md border px-2 py-1">
                {m.flow_run_transcription_files({ count: String(transcription.files_count ?? 0) })}
              </span>
              <span class="border-default bg-primary rounded-md border px-2 py-1">
                {m.flow_run_transcription_duration({
                  duration: formatElapsedMs(transcription.elapsed_ms)
                })}
              </span>
              <span class="border-default bg-primary rounded-md border px-2 py-1">
                {m.flow_run_transcription_size({ size: formatBytes(transcription.transcript_bytes) })}
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

        {#if isPowerUser && stepAttempts.length > 0}
          <div>
            <div class="flex items-center justify-between">
              <h4 class="text-muted text-xs font-semibold">{m.flow_run_attempts()}</h4>
              <button
                class="text-muted hover:bg-hover-default hover:text-secondary focus-visible:ring-accent-default rounded-md p-1.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                aria-label={m.copy()}
                on:click={() =>
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
            <pre
              class="border-accent-default bg-hover-dimmer mt-1 max-h-80 overflow-auto rounded-lg border-l-2 p-3 font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap">{JSON.stringify(
                stepAttempts,
                null,
                2
              )}</pre>
          </div>
        {/if}

        {#if result.num_tokens_input != null || result.num_tokens_output != null}
          <div class="border-default text-muted flex items-center gap-2 border-t pt-3 text-xs">
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
