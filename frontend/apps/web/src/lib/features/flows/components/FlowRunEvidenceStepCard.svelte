<script lang="ts">
  import type { FlowRunError, FlowRunResultFile, FlowRunStep, Eneo } from "@eneo/eneo-js";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconCopy } from "@eneo/icons/copy";
  import { IconCheck } from "@eneo/icons/check";
  import { Markdown } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import FlowRunKnowledgeTrace from "./FlowRunKnowledgeTrace.svelte";
  import FlowCitationSummary from "./FlowCitationSummary.svelte";
  import { readAttachedCitationSummary } from "./flowCitationSummary";
  import FlowJsonViewer from "./FlowJsonViewer.svelte";
  import FlowRunErrorAlert from "./FlowRunErrorAlert.svelte";
  import { isFailureRepairCandidate } from "$lib/features/flows/flowRunFailureRepair";
  import FlowRunResultFileButton from "./FlowRunResultFileButton.svelte";
  import FlowRunStatusBadge from "./FlowRunStatusBadge.svelte";
  import { formatFlowRunTokenCount } from "./flowRunTokenUsage";
  import { getLocale } from "$lib/paraglide/runtime";
  import TranscriptPlayer, { type SignedAudio } from "./TranscriptPlayer.svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import {
    isPureTranscript,
    parseTranscript,
    type TranscriptFileReview,
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
    speakerReviews?: TranscriptFileReview[];
    segments: TranscriptSegment[] | null;
    /** True while the paged transcript source is still being read. */
    loading?: boolean;
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
    onRepairFailure = null,
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
    /** Offered for a failure the AI Builder may repair; called with the step order. */
    onRepairFailure?: ((stepOrder: number) => void) | null;
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

  // A step that never searches knowledge has no trace to show: a row of zeros
  // ("Källor: 0 · Hämtade segment: 0") only made the reader wonder what was
  // missing. A search that was set up but skipped or failed still shows.
  const NO_KNOWLEDGE_SEARCH = new Set([
    "",
    "skipped",
    "skipped_no_knowledge",
    "skipped_transcribe_only"
  ]);
  const showKnowledgeTrace = $derived(
    stepRag !== null && !NO_KNOWLEDGE_SEARCH.has(String(stepRag.status ?? ""))
  );

  // A step after the one that stopped the run (the run error names it) is
  // recorded as failed with the run's error, but it never started. It reads as "did not run", and the error is
  // shown once, on the step that actually failed.
  const neverStarted = $derived(
    result.status === "failed" &&
      !result.started_at &&
      typeof runError?.step_order === "number" &&
      runError.step_order !== result.step_order
  );
  const stepReviewPolicy = $derived(stepDef?.review_policy ?? null);
  const shouldShowStepError = $derived(
    result.error_message && !neverStarted
      ? isReviewPolicyRunErrorRelevantForStep(runError, result.step_order, stepReviewPolicy)
      : false
  );

  let inputOpen = $state(false);
  // A long prompt is bounded so it cannot swamp the card, but the bound cut the
  // text mid-line with nothing to say there was more.
  let promptExpanded = $state(false);
  let promptEl = $state<HTMLPreElement | null>(null);
  let promptClipped = $state(false);
  $effect(() => {
    const element = promptEl;
    if (!element) return;
    void result.effective_prompt;
    void promptExpanded;
    promptClipped = element.scrollHeight > element.clientHeight + 1;
  });
  const hasResultFiles = $derived(resultFiles.length > 0);
  // A step whose answer broke its format stores that answer as one escaped
  // string. It is diagnostic material: shown decoded, labelled as the answer
  // that was not accepted, and only in Avancerad; the error above explains it.
  const rejectedOutput = $derived.by(() => {
    const raw = (result.output_payload_json as Record<string, unknown> | null | undefined)
      ?.rejected_output;
    if (typeof raw !== "string") return null;
    try {
      return { value: JSON.parse(raw) as unknown };
    } catch {
      return { value: raw as unknown };
    }
  });

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

<Card.Root class="gap-0 overflow-hidden py-0">
  <button
    type="button"
    class="hover:bg-hover-dimmer focus-visible:inset-ring-ring flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left focus-visible:inset-ring-2 focus-visible:outline-none"
    aria-expanded={expanded}
    aria-controls={panelId}
    onclick={() => onToggle(result.step_order)}
  >
    <div class="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
      <span
        class="bg-hover-dimmer flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums"
      >
        {result.step_order}
      </span>
      <span class="min-w-0 text-sm font-medium [overflow-wrap:anywhere]">
        {stepDef?.user_description ??
          m.flow_step_fallback_label({ order: String(result.step_order) })}
      </span>
      {#if neverStarted}
        <Badge variant="outline" class="text-secondary h-5 px-1.5 text-xs font-medium">
          {m.flow_run_step_not_run()}
        </Badge>
      {:else}
        <FlowRunStatusBadge status={result.status} size="xs" />
      {/if}
      {#if duration}
        <span class="text-secondary text-xs tabular-nums">{duration}</span>
      {/if}
    </div>
    <span
      class="motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out)"
      class:rotate-180={expanded}
    >
      <IconChevronDown class="size-4" aria-hidden="true" />
    </span>
  </button>

  {#if expanded}
    <div id={panelId}>
      <Card.Content class="border-default flex min-w-0 flex-col gap-4 border-t px-5 py-4">
        <!-- What went wrong leads, then what the step produced; how it was asked
             (prompt, input) follows for whoever needs to dig. -->
        {#if result.error_message && shouldShowStepError}
          <FlowRunErrorAlert
            error={runError}
            errorCode={result.error_code}
            message={result.error_message}
            steps={reviewPolicyDefinitionSteps.filter(
              (step) => step.step_order === result.step_order
            )}
            onrepair={onRepairFailure && isFailureRepairCandidate(result.error_code)
              ? () => onRepairFailure(result.step_order)
              : null}
          />
        {/if}
        {#if result.output_payload_json && (rejectedOutput === null || isPowerUser)}
          <!-- 68ch is the right measure for prose output, and the wrong one
               for a transcript: the player is a scrubber plus three columns
               of timestamp, speaker and text, and it was being squeezed into
               a reading column about a third of the card. The cap follows
               what the block actually holds. -->
          <div
            class={transcriptSegments && transcriptContext && !hasResultFiles
              ? "min-w-0"
              : "max-w-[68ch]"}
          >
            <div class="flex items-center justify-between">
              <h4 class="text-secondary text-xs font-semibold">
                {rejectedOutput ? m.flow_run_rejected_output_title() : m.flow_run_output()}
              </h4>
              <Button
                variant="ghost"
                size="icon"
                class="text-secondary hover:text-primary size-8"
                aria-label={m.copy()}
                onclick={() =>
                  void onCopyPayload(
                    `step-${result.step_order}-output`,
                    result.output_payload_json,
                    m.flow_run_copy_failed()
                  )}
              >
                {#if copiedKey === `step-${result.step_order}-output`}
                  <IconCheck class="text-positive-stronger size-3.5" />
                {:else}
                  <IconCopy class="size-3.5" />
                {/if}
              </Button>
            </div>

            {#if speakerMapping.length > 0}
              <div class="mt-1">
                <h4 class="text-secondary text-xs font-semibold">
                  {m.flow_step_speaker_mapping_section()}
                </h4>
                <ul class="divide-default mt-1.5 divide-y rounded-lg border p-0">
                  {#each speakerMapping as row (row.label)}
                    <li class="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 px-3 py-2">
                      <span class="text-secondary font-mono text-xs">{row.label}</span>
                      <span class="text-sm font-medium" class:text-secondary={row.name === null}>
                        {row.name ?? m.flow_run_transcript_unknown_speaker()}
                      </span>
                      <Badge variant="outline" class="text-xs">
                        {confidenceText(row.confidence)}
                      </Badge>
                      {#if row.evidence}
                        <span class="text-secondary basis-full text-xs text-pretty sm:basis-auto">
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
                {#if isPowerUser}
                  <Badge class="bg-accent-dimmer text-accent-stronger mb-1">
                    {m.flow_run_structured_json_badge()}
                  </Badge>
                {/if}
                <FlowJsonViewer value={result.output_payload_json.structured} className="mt-0" />
              </div>
            {/if}

            {#if hasResultFiles}
              <div class="mt-2">
                <h4 class="text-secondary text-xs font-semibold">{m.flow_run_files()}</h4>
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
              {#if !ownsStoredSegments}
                <p class="text-secondary text-xs">
                  {m.flow_transcript_review_details_unavailable()}
                </p>
              {:else if correctionsController?.speakerEdits.length}
                <p class="text-secondary text-xs">
                  {m.flow_transcript_review_regenerate()}
                </p>
              {/if}
              {#if ownsStoredSegments && transcriptContext?.loading && !transcriptContext.segments}
                <p class="text-secondary text-sm" aria-live="polite">
                  {m.flow_run_evidence_transcript_loading()}
                </p>
              {/if}
              <TranscriptPlayer
                reviewEditor
                speakerReviews={ownsStoredSegments ? transcriptContext.speakerReviews : []}
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
            {:else if rejectedOutput}
              <FlowJsonViewer value={rejectedOutput.value} />
            {:else if !result.output_payload_json.structured && !hasResultFiles}
              <FlowJsonViewer value={result.output_payload_json} />
            {/if}
          </div>
        {/if}

        <!-- Plain sections under a heading, like Resultat above: a card inside
             the step card was one box too many. Engine facts (model, byte
             size, token estimate, file format) are for Avancerad. -->
        {#if runtimeInput}
          <section>
            <h4 class="text-secondary text-xs font-semibold">
              {m.flow_run_runtime_input_label()}
            </h4>
            <div class="mt-1.5 flex flex-wrap gap-2 text-xs">
              <Badge variant="outline">
                {getRuntimeInputSummaryLabel(runtimeInput.fileCount)}
              </Badge>
              {#if runtimeInput.extractedTextLength != null}
                <Badge variant="outline" class="tabular-nums">
                  {m.flow_run_extracted_text_badge({
                    count: runtimeInput.extractedTextLength.toLocaleString(getLocale())
                  })}
                </Badge>
              {/if}
              {#if isPowerUser && runtimeInput.inputFormat}
                <Badge variant="outline">
                  {m.flow_run_input_format_badge({ format: runtimeInput.inputFormat })}
                </Badge>
              {/if}
            </div>
          </section>
        {/if}

        {#if transcription}
          <section>
            <h4 class="text-secondary text-xs font-semibold">
              {m.flow_run_transcription_label()}
            </h4>
            <dl class="mt-1.5 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
              <dt class="text-secondary">{m.flow_run_transcription_files()}</dt>
              <dd class="tabular-nums">{transcription.files_count ?? 0}</dd>
              <dt class="text-secondary">{m.flow_run_transcription_language()}</dt>
              <dd>{transcription.language ?? "\u2014"}</dd>
              <dt class="text-secondary">{m.flow_run_transcription_duration()}</dt>
              <dd class="tabular-nums">{formatElapsedMs(transcription.elapsed_ms)}</dd>
              {#if isPowerUser}
                <dt class="text-secondary">{m.flow_run_transcription_model()}</dt>
                <dd class="break-all">{transcription.model ?? "\u2014"}</dd>
                <dt class="text-secondary">{m.flow_run_transcription_size()}</dt>
                <dd class="tabular-nums">{formatBytes(transcription.transcript_bytes)}</dd>
                <dt class="text-secondary">{m.flow_run_transcription_estimated_tokens()}</dt>
                <dd class="tabular-nums">
                  {formatFlowRunTokenCount(transcription.estimated_tokens ?? 0, getLocale())}
                </dd>
              {/if}
            </dl>
            {#if transcription.diarization === "external" && (transcription.alignment === "segment_split" || transcription.alignment === "segment_only")}
              <p class="text-warning-stronger mt-1.5 text-xs">
                {m.flow_run_transcription_speakers_reduced_precision()}
              </p>
            {:else if transcription.diarization === "external"}
              <p class="text-secondary mt-1.5 text-xs">
                {m.flow_run_transcription_speakers_labelled({
                  duration: formatElapsedMs(transcription.diarization_elapsed_ms ?? undefined)
                })}
              </p>
            {:else if transcription.diarization?.startsWith("skipped")}
              <p class="text-warning-stronger mt-1.5 text-xs">
                {m.flow_run_transcription_speakers_skipped()}
              </p>
            {/if}
          </section>
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
        {#if showKnowledgeTrace}
          <FlowRunKnowledgeTrace rag={stepRag} stepOrder={result.step_order} {eneo} />
        {/if}

        {#if result.effective_prompt}
          <div class="max-w-[68ch]">
            <div class="flex items-center justify-between">
              <h4 class="text-secondary text-xs font-semibold">{m.flow_run_effective_prompt()}</h4>
              <Button
                variant="ghost"
                size="icon"
                class="text-secondary hover:text-primary size-8"
                aria-label={m.copy()}
                onclick={() =>
                  void onCopyPayload(
                    `step-${result.step_order}-prompt`,
                    result.effective_prompt,
                    m.flow_run_copy_failed()
                  )}
              >
                {#if copiedKey === `step-${result.step_order}-prompt`}
                  <IconCheck class="text-positive-stronger size-3.5" />
                {:else}
                  <IconCopy class="size-3.5" />
                {/if}
              </Button>
            </div>
            <pre
              bind:this={promptEl}
              class="bg-hover-dimmer mt-1.5 overflow-hidden rounded-lg p-3 font-sans text-sm leading-relaxed break-words whitespace-pre-wrap {promptExpanded
                ? ''
                : 'max-h-80'}">{result.effective_prompt}</pre>
            {#if result.effective_prompt_truncated}
              <p class="text-secondary mt-1.5 text-xs">{m.flow_run_effective_prompt_truncated()}</p>
            {/if}
            {#if promptClipped || promptExpanded}
              <Button
                variant="link"
                size="sm"
                class="text-accent-stronger mt-1 h-auto min-h-[24px] px-0 py-1"
                aria-expanded={promptExpanded}
                onclick={() => (promptExpanded = !promptExpanded)}
              >
                {promptExpanded
                  ? m.flow_run_effective_prompt_show_less()
                  : m.flow_run_effective_prompt_show_all()}
              </Button>
            {/if}
          </div>
        {/if}

        {#if isPowerUser && result.input_payload_json}
          <Collapsible.Root bind:open={inputOpen}>
            <div class="flex items-center justify-between">
              <Collapsible.Trigger
                class="text-secondary hover:text-primary focus-visible:ring-ring -ml-1 flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-semibold transition-colors focus-visible:ring-2 focus-visible:outline-none"
                aria-expanded={inputOpen}
                aria-controls="step-{result.step_order}-input-panel"
              >
                <IconChevronDown
                  class="size-3 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {inputOpen
                    ? 'rotate-180'
                    : ''}"
                  aria-hidden="true"
                />
                {inputOpen ? m.flow_run_hide_input() : m.flow_run_show_input()}
              </Collapsible.Trigger>
              <Button
                variant="ghost"
                size="icon"
                class="text-secondary hover:text-primary size-8"
                aria-label={m.flow_run_copy_input()}
                onclick={() =>
                  void onCopyPayload(
                    `step-${result.step_order}-input`,
                    result.input_payload_json,
                    m.flow_run_copy_failed()
                  )}
              >
                {#if copiedKey === `step-${result.step_order}-input`}
                  <IconCheck class="text-positive-stronger size-3.5" />
                {:else}
                  <IconCopy class="size-3.5" />
                {/if}
              </Button>
            </div>
            <Collapsible.Content>
              <div id="step-{result.step_order}-input-panel">
                <FlowJsonViewer value={result.input_payload_json} />
              </div>
            </Collapsible.Content>
          </Collapsible.Root>
        {/if}

        {#if templateProvenance}
          <section>
            <h4 class="text-secondary text-xs font-semibold">
              {m.flow_run_template_provenance_label()}
            </h4>
            <div class="mt-1.5 flex flex-wrap gap-2 text-xs">
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
              {#if isPowerUser && templateProvenance.templateAssetId}
                <Badge variant="outline">
                  {m.flow_run_template_asset_badge({ id: templateProvenance.templateAssetId })}
                </Badge>
              {/if}
              {#if isPowerUser && templateProvenance.templateFileId}
                <Badge variant="outline">
                  {m.flow_run_template_file_badge({ id: templateProvenance.templateFileId })}
                </Badge>
              {/if}
              {#if isPowerUser && templateProvenance.checksum}
                <Badge variant="outline">
                  {templateProvenance.checksum}
                </Badge>
              {/if}
            </div>
          </section>
        {/if}

        {#if isPowerUser && stepAttempts.length > 0}
          <div>
            <div class="flex items-center justify-between">
              <h4 class="text-secondary text-xs font-semibold">{m.flow_run_attempts()}</h4>
              <Button
                variant="ghost"
                size="icon"
                class="text-secondary hover:text-primary size-8"
                aria-label={m.copy()}
                onclick={() =>
                  void onCopyPayload(
                    `step-${result.step_order}-attempts`,
                    stepAttempts,
                    m.flow_run_copy_failed()
                  )}
              >
                {#if copiedKey === `step-${result.step_order}-attempts`}
                  <IconCheck class="text-positive-stronger size-3.5" />
                {:else}
                  <IconCopy class="size-3.5" />
                {/if}
              </Button>
            </div>
            <FlowJsonViewer value={stepAttempts} maxHeightClass="max-h-[300px]" />
          </div>
        {/if}

        <!-- The run summary carries the explained total; per-step counts are
             for Avancerad. -->
        {#if isPowerUser && (result.num_tokens_input ?? 0) + (result.num_tokens_output ?? 0) > 0}
          <div class="border-default text-secondary flex items-center gap-2 border-t pt-3 text-xs">
            <span>{m.flow_run_tokens()}</span>
            <span aria-hidden="true">&middot;</span>
            <span class="tabular-nums"
              >{m.flow_run_tokens_in({
                count: formatFlowRunTokenCount(result.num_tokens_input ?? 0, getLocale())
              })}</span
            >
            <span aria-hidden="true">&middot;</span>
            <span class="tabular-nums"
              >{m.flow_run_tokens_out({
                count: formatFlowRunTokenCount(result.num_tokens_output ?? 0, getLocale())
              })}</span
            >
          </div>
        {/if}
      </Card.Content>
    </div>
  {/if}
</Card.Root>
