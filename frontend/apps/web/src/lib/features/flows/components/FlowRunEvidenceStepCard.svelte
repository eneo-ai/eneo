<script lang="ts">
  import type { FlowRunError, FlowRunResultFile, FlowRunStep, Eneo } from "@eneo/eneo-js";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconCopy } from "@eneo/icons/copy";
  import { IconCheck } from "@eneo/icons/check";
  import { Markdown } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import FlowRunKnowledgeTrace from "./FlowRunKnowledgeTrace.svelte";
  import FlowCitationSummary from "./FlowCitationSummary.svelte";
  import { readAttachedCitationSummary } from "./flowCitationSummary";
  import FlowJsonViewer from "./FlowJsonViewer.svelte";
  import FlowRunErrorAlert from "./FlowRunErrorAlert.svelte";
  import FlowRunResultFileButton from "./FlowRunResultFileButton.svelte";
  import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";
  import TranscriptPlayer, { type SignedAudio } from "./TranscriptPlayer.svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import {
    isPureTranscript,
    parseTranscript,
    type TranscriptSegment
  } from "$lib/features/flows/transcriptSegments";
  import {
    buildSpeakerRows,
    speakerNamesFromRows,
    type SpeakerConfidence
  } from "$lib/features/flows/speakerMappingReview";
  import type { TranscriptCorrectionsController } from "$lib/features/flows/transcriptCorrectionsController.svelte";
  import {
    isReviewPolicyRunErrorRelevantForStep,
    type FlowReviewPolicyErrorStep
  } from "$lib/features/flows/flowRuntimeErrorMapping";
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
    /** null: no speaker labels requested; "external": labelled; "skipped:<reason>". */
    diarization?: string | null;
    diarization_elapsed_ms?: number | null;
    /** forced | segment_split | segment_only, from the service. */
    alignment?: string | null;
    /** Audio files read, in the order their timestamps restart. */
    file_ids?: string[];
    /** Structured transcript lines; null when the step stored none. */
    segments?: unknown;
  };

  /** Audio and segments of the run's transcription step, shared by every card. */
  export type FlowRunTranscriptContext = {
    fileIds: string[];
    segments: TranscriptSegment[] | null;
    /** The transcription step the segments (and any corrections) anchor to. */
    stepId: string | null;
    getAudioUrl: (fileIndex: number) => Promise<SignedAudio>;
  };

  let {
    result,
    currentEvidenceNotLoaded = false,
    resultFiles = [],
    stepDef,
    duration,
    transcription,
    runtimeInput,
    templateProvenance,
    stepRag,
    stepAttempts,
    runError = null,
    reviewPolicyDefinitionSteps = [],
    transcriptContext = null,
    correctionsController = null,
    copiedKey,
    expanded,
    panelId,
    isPowerUser,
    eneo,
    onToggle,
    onCopyPayload,
    onDownloadArtifact,
    getRuntimeInputSummaryLabel,
    formatElapsedMs,
    formatBytes
  }: {
    result: FlowRunStep;
    currentEvidenceNotLoaded?: boolean;
    resultFiles?: FlowRunResultFile[];
    stepDef: Record<string, unknown> | undefined;
    duration: string | null;
    transcription: FlowRunTranscriptionTelemetry | null;
    runtimeInput: RuntimeInputSummary | null;
    templateProvenance: TemplateProvenanceSummary | null;
    stepRag: Record<string, unknown> | null;
    stepAttempts: Record<string, unknown>[];
    runError?: FlowRunError | null;
    reviewPolicyDefinitionSteps?: readonly FlowReviewPolicyErrorStep[];
    transcriptContext?: FlowRunTranscriptContext | null;
    /** Shared transcript-corrections lifecycle; null disables editing. */
    correctionsController?: TranscriptCorrectionsController | null;
    copiedKey: string | null;
    expanded: boolean;
    panelId: string;
    isPowerUser: boolean;
    eneo: Eneo;
    onToggle: (stepOrder: number) => void;
    onCopyPayload: (key: string, payload: unknown, failureMessage: string) => Promise<void>;
    onDownloadArtifact: (fileId: string) => Promise<void>;
    getRuntimeInputSummaryLabel: (fileCount: number) => string;
    formatElapsedMs: (value: number | undefined) => string;
    formatBytes: (value: number | undefined) => string;
  } = $props();

  // The backend attaches the citation summary to the step result when the
  // step had citation mode on; a malformed payload parses to null and the
  // section simply does not render (server owns the off-vs-unavailable
  // distinction).
  const citationSummary = $derived(readAttachedCitationSummary(result));

  const stepReviewPolicy = $derived(stepDef?.review_policy ?? null);
  const shouldShowStepError = $derived(
    result.error_message
      ? isReviewPolicyRunErrorRelevantForStep(runError, result.step_order, stepReviewPolicy)
      : false
  );

  let inputOpen = $state(false);
  const hasResultFiles = $derived(resultFiles.length > 0);

  const outputText = $derived(
    typeof result.output_payload_json?.text === "string" ? result.output_payload_json.text : ""
  );
  // The mapping the step produced, one row per diarized label, read through
  // the same parser the review checkpoint uses (the `speaker_mapping`
  // extension is the discriminator: ordinary JSON with a `speakers` key is
  // not a mapping). Rendered once the step is done: the review that named the
  // speakers is gone by then, and raw JSON is not an answer to "who is who".
  const speakerMapping = $derived(buildSpeakerRows(result.output_payload_json ?? null));
  const transcriptSpeakerNames = $derived(speakerNamesFromRows(speakerMapping));
  // The stored segments (word timings, corrections, speaker edits) belong to
  // the transcription step and to the speaker-mapping step whose text is that
  // transcript with names; those two cards render them, the mapping supplying
  // the names. Every other step shows its own output: a player when that
  // output is a pure transcript (its lines already carry the names), and the
  // plain text otherwise, so a composed document is shown as authored.
  const ownsStoredSegments = $derived(
    transcriptContext !== null &&
      transcriptContext !== undefined &&
      (result.step_id === transcriptContext.stepId || speakerMapping.length > 0)
  );
  const transcriptSegments = $derived.by(() => {
    if (!transcriptContext || !outputText) return null;
    const parsed = parseTranscript(outputText);
    if (parsed.length === 0) return null;
    if (ownsStoredSegments) return transcriptContext.segments ?? parsed;
    return isPureTranscript(outputText) ? parsed : null;
  });
  function confidenceText(confidence: SpeakerConfidence): string {
    if (confidence === "high") return m.flow_run_review_speakers_confidence_high();
    if (confidence === "medium") return m.flow_run_review_speakers_confidence_medium();
    return m.flow_run_review_speakers_confidence_low();
  }
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

            {#if speakerMapping.length > 0}
              <div class="mt-1">
                <h4 class="text-muted text-xs font-semibold">
                  {m.flow_step_speaker_mapping_section()}
                </h4>
                <ul class="divide-default mt-1.5 divide-y rounded-lg border p-0">
                  {#each speakerMapping as row (row.label)}
                    <li class="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 px-3 py-2">
                      <span class="text-secondary font-mono text-xs">{row.label}</span>
                      <span class="text-sm font-medium" class:text-muted={row.name === null}>
                        {row.name ?? m.flow_run_transcript_unknown_speaker()}
                      </span>
                      <Badge variant="outline" class="text-xs">
                        {confidenceText(row.confidence)}
                      </Badge>
                      {#if row.evidence}
                        <span class="text-muted basis-full text-xs text-pretty sm:basis-auto">
                          {row.evidence}
                        </span>
                      {/if}
                    </li>
                  {/each}
                </ul>
              </div>
            {/if}

            {#if result.output_payload_json.structured}
              <div class="mt-1">
                <Badge class="bg-accent-dimmer text-accent-stronger mb-1">
                  {m.flow_run_structured_json_badge()}
                </Badge>
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

            {#if transcriptSegments && transcriptContext && !hasResultFiles}
              {#if correctionsController?.error}
                <Alert.Root variant="destructive" class="mt-1">
                  <Alert.Description class="text-xs">
                    {correctionsController.error}
                  </Alert.Description>
                </Alert.Root>
              {/if}
              {#if correctionsController && correctionsController.staleCount > 0}
                <Alert.Root class="mt-1">
                  <Alert.Description class="text-xs">
                    {m.flow_run_transcript_corrections_stale({
                      count: String(correctionsController.staleCount)
                    })}
                  </Alert.Description>
                </Alert.Root>
              {/if}
              <TranscriptPlayer
                segments={transcriptSegments}
                fileCount={transcriptContext.fileIds.length}
                getAudioUrl={transcriptContext.getAudioUrl}
                speakerNames={transcriptSpeakerNames}
                textFallback={outputText}
                corrections={ownsStoredSegments ? (correctionsController?.occurrences ?? []) : []}
                speakerEdits={ownsStoredSegments ? (correctionsController?.speakerEdits ?? []) : []}
                class="mt-1"
              />
            {:else if result.output_payload_json.text && !result.output_payload_json.structured && !hasResultFiles}
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
              <div class="text-secondary mt-2 flex flex-wrap gap-2 text-xs">
                <Badge variant="outline">
                  {getRuntimeInputSummaryLabel(runtimeInput.fileCount)}
                </Badge>
                {#if runtimeInput.inputFormat}
                  <Badge variant="outline">
                    {m.flow_run_input_format_badge({ format: runtimeInput.inputFormat })}
                  </Badge>
                {/if}
                {#if runtimeInput.extractedTextLength != null}
                  <Badge variant="outline">
                    {m.flow_run_extracted_text_badge({
                      count: String(runtimeInput.extractedTextLength)
                    })}
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
              <div class="text-secondary mt-2 flex flex-wrap gap-2 text-xs">
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
                {#if transcription.diarization === "external" && (transcription.alignment === "segment_split" || transcription.alignment === "segment_only")}
                  <Badge variant="outline" class="border-warning-default/40 text-warning-stronger">
                    {m.flow_run_transcription_speakers_reduced_precision()}
                  </Badge>
                {:else if transcription.diarization === "external"}
                  <Badge variant="outline" class="border-accent-default/40 text-accent-stronger">
                    {m.flow_run_transcription_speakers_labelled({
                      duration: formatElapsedMs(transcription.diarization_elapsed_ms ?? undefined)
                    })}
                  </Badge>
                {:else if transcription.diarization?.startsWith("skipped")}
                  <Badge variant="outline" class="border-warning-default/40 text-warning-stronger">
                    {m.flow_run_transcription_speakers_skipped()}
                  </Badge>
                {/if}
              </div>
            </Card.Content>
          </Card.Root>
        {/if}

        {#if currentEvidenceNotLoaded}
          <p class="text-secondary text-xs italic" data-testid="current-evidence-not-loaded">
            {m.flow_run_step_current_evidence_not_loaded()}
          </p>
        {/if}
        {#if citationSummary}
          <div class="border-default bg-primary rounded-lg border p-3">
            <FlowCitationSummary summary={citationSummary} />
          </div>
        {/if}
        {#if stepRag}
          <FlowRunKnowledgeTrace rag={stepRag} stepOrder={result.step_order} {eneo} />
        {/if}

        {#if templateProvenance}
          <Card.Root size="sm" class="bg-hover-dimmer">
            <Card.Content class="p-3">
              <h4 class="text-muted text-xs font-semibold">
                {m.flow_run_template_provenance_label()}
              </h4>
              <div class="text-secondary mt-2 flex flex-col gap-2 text-xs">
                <div class="flex flex-wrap gap-2">
                  <Badge variant="outline">
                    {templateProvenance.templateName}
                  </Badge>
                  {#if templateProvenance.publishedFlowVersion != null}
                    <Badge variant="outline">
                      {m.flow_run_template_version_badge({
                        version: String(templateProvenance.publishedFlowVersion)
                      })}
                    </Badge>
                  {/if}
                </div>
                <div class="flex flex-wrap gap-2">
                  {#if templateProvenance.templateAssetId}
                    <Badge variant="outline">
                      {m.flow_run_template_asset_badge({ id: templateProvenance.templateAssetId })}
                    </Badge>
                  {/if}
                  {#if templateProvenance.templateFileId}
                    <Badge variant="outline">
                      {m.flow_run_template_file_badge({ id: templateProvenance.templateFileId })}
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

        {#if result.error_message && shouldShowStepError}
          <FlowRunErrorAlert
            error={runError}
            errorCode={result.error_code}
            message={result.error_message}
            steps={reviewPolicyDefinitionSteps.filter(
              (step) => step.step_order === result.step_order
            )}
          />
        {/if}
      </Card.Content>
    </div>
  {/if}
</Card.Root>
