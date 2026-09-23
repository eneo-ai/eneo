<script lang="ts">
  import type {
    Eneo,
    FlowRunContractStepInput,
    FlowRunContractTranscription,
    UploadedFile
  } from "@eneo/eneo-js";
  import { onDestroy } from "svelte";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import ChevronRight from "lucide-svelte/icons/chevron-right";
  import { IconUploadCloud } from "@eneo/icons/upload-cloud";
  import { IconXMark } from "@eneo/icons/x-mark";
  import { IconCheck } from "@eneo/icons/check";
  import { IconDownload } from "@eneo/icons/download";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    classifyUploadError,
    getUploadErrorHint,
    friendlyMimeNames
  } from "$lib/features/flows/flowRuntimeErrorMapping";
  import AudioRecorder from "$lib/features/audio/AudioRecorder.svelte";
  import LiveTranscriptPanel from "$lib/features/audio/live/LiveTranscriptPanel.svelte";
  import {
    LiveTranscriptPreview,
    type RecorderAudioGraph
  } from "$lib/features/audio/live/LiveTranscriptPreview.svelte";
  import type { RecordingStopReason } from "$lib/features/audio/recordedAudioFile";
  import type { SessionRecoveryHint } from "$lib/features/audio/recordingSessionStore";
  import { formatBytes } from "$lib/features/flows/flowByteSize";
  import type { FlowRunDialogLabels } from "./flowRunDialogLabels";
  import type { FlowRunLaunchInputState } from "./FlowRunLaunchInputState.svelte";
  import FlowRunResumePrompt from "./FlowRunResumePrompt.svelte";
  import FlowRunStorageDegradedNotice from "./FlowRunStorageDegradedNotice.svelte";

  let {
    step,
    eneo,
    flowId,
    transcription,
    launchInputState,
    recording,
    files,
    hasFailedRecording,
    recorderResetToken,
    fileCount,
    remainingSlots,
    isUploading,
    uploadError,
    recordingNotice,
    skippedMessage,
    dragging,
    labels,
    locale,
    resumeHint = null,
    showResumePrompt = false,
    resumeBusy = false,
    storageDegraded = false,
    canStartRecording = true,
    canDiscardRecording = true,
    sessionPhase = "idle",
    onOpenFilePicker,
    onRemoveFile,
    onDownloadUploadedFile,
    onRetryUpload,
    onDownloadRecordedAudio,
    onRetryRecordedAudio,
    onDiscardRecordedAudio,
    onSaveForLater,
    onContinueResume,
    onDiscardResume,
    onDismissResumePrompt,
    onRecordingDone,
    onRecordingStateChange,
    onRecorderRef,
    onSessionRetry,
    onSessionDismissFailure,
    onDrop,
    onDragOver,
    onDragLeave
  }: {
    step: FlowRunContractStepInput;
    eneo: Eneo;
    flowId: string;
    // The flow's transcription options from the run contract; null when the
    // flow transcribes no audio.
    transcription: FlowRunContractTranscription | null;
    launchInputState: FlowRunLaunchInputState;
    // Whether this step's recorder is recording.
    recording: boolean;
    files: UploadedFile[];
    // Recorded segments whose upload failed are waiting for Retry.
    hasFailedRecording: boolean;
    recorderResetToken: number;
    fileCount: number;
    remainingSlots: number;
    isUploading: boolean;
    uploadError: string | null;
    recordingNotice: string | null;
    skippedMessage: string | null;
    dragging: boolean;
    labels: FlowRunDialogLabels;
    locale: "sv" | "en";
    resumeHint?: SessionRecoveryHint | null;
    showResumePrompt?: boolean;
    resumeBusy?: boolean;
    storageDegraded?: boolean;
    canStartRecording?: boolean;
    // False while the step's recording or an upload is still on its way.
    canDiscardRecording?: boolean;
    // The session-level state surfaces a "trying to reconnect" hint and a
    // paused-failed CTA right next to the recorder so the user knows the
    // system is still working without scrolling.
    sessionPhase?: "idle" | "reconnecting" | "paused-failed";
    onOpenFilePicker: () => void;
    onRemoveFile: (fileId: string) => void;
    onDownloadUploadedFile: (file: UploadedFile) => void;
    onRetryUpload: () => void;
    onDownloadRecordedAudio: () => void;
    onRetryRecordedAudio: () => void;
    onDiscardRecordedAudio: () => void;
    onSaveForLater?: () => void;
    onContinueResume?: (hint: SessionRecoveryHint) => void;
    onDiscardResume?: (hint: SessionRecoveryHint) => void;
    onDismissResumePrompt?: () => void;
    onRecordingDone: (params: {
      blob: Blob | null;
      mimeType: string;
      reason: RecordingStopReason;
      durationMs: number;
    }) => void;
    onRecordingStateChange?: (isRecording: boolean, meta?: { origin: "user" | "external" }) => void;
    // Lets the dialog grab an imperative handle on the recorder so the
    // session controller can call startExternal/stopExternal during retries.
    onRecorderRef?: (
      stepId: string,
      ref: {
        startExternal: () => Promise<void>;
        stopExternal: (reason?: RecordingStopReason) => Promise<void>;
      } | null
    ) => void;
    onSessionRetry?: () => void;
    onSessionDismissFailure?: () => void;
    onDrop: (event: DragEvent) => void;
    onDragOver: (event: DragEvent) => void;
    onDragLeave: (event: DragEvent) => void;
  } = $props();

  function getStepLabel(s: FlowRunContractStepInput): string {
    return s.label?.trim() || labels.unnamedStep(s.step_order);
  }

  function getInputFormatLabel(inputFormat: string): string {
    switch (inputFormat) {
      case "audio":
        return labels.audio;
      case "file":
        return labels.file;
      default:
        return labels.document;
    }
  }

  const DISCARD_REASON_ID = "flow-run-discard-reason";
  const supportsAudioRecording = $derived(step.input_format === "audio");
  const acceptedMimetypes = $derived(step.accepted_mimetypes ?? []);

  let recorderRef = $state<{
    startExternal: () => Promise<void>;
    stopExternal: (reason?: RecordingStopReason) => Promise<void>;
  } | null>(null);

  // Push the live ref up to the dialog every time it changes so the
  // session controller (which lives in the dialog) can call back into
  // this recorder. Returning a teardown clears the ref on unmount.
  //
  // The optional-chained read on `step` guards a Svelte 5 lifecycle race
  // during dialog close: the parent's reset clears `currentRuntimeStep`
  // synchronously while bits-ui is still tearing down the content tree, so
  // the AudioRecorder's bind:this nullification re-fires this effect after
  // the prop has already gone away. Bail out before touching `step` or any
  // derived that reads it.
  $effect(() => {
    const activeStepId = step?.step_id;
    if (!activeStepId || !supportsAudioRecording) return;
    onRecorderRef?.(activeStepId, recorderRef);
    return () => onRecorderRef?.(activeStepId, null);
  });

  // Drive the disclosure chevrons.
  let allowedTypesOpen = $state(false);
  let technicalMimeOpen = $state(false);

  const uid = $props.id();
  const liveTextAvailable = $derived(transcription?.live.available === true);
  const liveTextOn = $derived(liveTextAvailable && launchInputState.liveTextOn);
  const speakerLabels = $derived(launchInputState.speakerLabels(transcription));

  // The preview listens to the recorder's audio graph, which exists from the
  // moment the microphone opens until the recording is over.
  const livePreview = new LiveTranscriptPreview();
  let recorderAudioGraph = $state.raw<RecorderAudioGraph | null>(null);

  function handleAudioGraph(graph: RecorderAudioGraph | null) {
    recorderAudioGraph = graph;
    if (!graph) {
      livePreview.stop();
    } else if (liveTextOn) {
      void livePreview.start(graph, {
        eneo,
        flowId,
        stepId: step.step_id,
        onListening: () => launchInputState.markLiveSessionStarted()
      });
    }
  }

  onDestroy(() => livePreview.dispose());
</script>

<div class="flex flex-col gap-5">
  <div class="px-1">
    {#if showResumePrompt && resumeHint && onContinueResume && onDiscardResume && onDismissResumePrompt}
      <FlowRunResumePrompt
        hint={resumeHint}
        busy={resumeBusy}
        {locale}
        onContinue={onContinueResume}
        onDiscard={onDiscardResume}
        onDismiss={onDismissResumePrompt}
      />
    {/if}

    {#if storageDegraded}
      <FlowRunStorageDegradedNotice />
    {/if}

    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <!-- The card is visibly an upload: it carries the field name, its
             description and its limits, and the line above already says which
             step the material belongs to. A label repeating that is the fourth
             statement of the same fact on one screen. The badges stay: they
             carry information the rest of the card does not. -->
        <div class="flex flex-wrap items-center gap-2">
          {#if step.required}
            <span
              class="border-default bg-secondary/15 text-secondary rounded-full border px-2 py-0.5 text-xs font-medium"
            >
              {labels.requiredBadge}
            </span>
          {/if}
          {#if fileCount > 0}
            <span
              class="border-positive-default/30 bg-positive-dimmer/50 text-positive-stronger rounded-full border px-2 py-0.5 text-xs font-medium"
            >
              {labels.selectedFiles(fileCount)}
            </span>
          {/if}
        </div>
        <p class="mt-2 text-base font-semibold">{getStepLabel(step)}</p>
        {#if step.description}
          <p class="text-secondary mt-1 text-sm leading-relaxed">
            {step.description}
          </p>
        {/if}
      </div>
      <div class="text-secondary flex flex-wrap gap-2 text-xs">
        <span class="border-default rounded-full border px-2 py-0.5">
          {getInputFormatLabel(step.input_format)}
        </span>
        {#if step.max_files != null}
          <span class="border-default rounded-full border px-2 py-0.5">
            {labels.maxFiles(step.max_files)}
          </span>
        {/if}
        {#if step.max_file_size_bytes != null}
          <span class="border-default rounded-full border px-2 py-0.5">
            {labels.maxFileSize(formatBytes(step.max_file_size_bytes))}
          </span>
        {/if}
      </div>
    </div>

    {#if isUploading}
      <div
        class="border-accent-default/30 bg-accent-dimmer text-accent-stronger mt-5 flex items-center gap-2 rounded-lg border px-3.5 py-2.5 text-sm"
        role="status"
        aria-live="polite"
      >
        <IconLoadingSpinner class="size-4 shrink-0 animate-spin" />
        {labels.runtimeUploadingHint}
      </div>
    {/if}

    {#snippet uploadArea()}
      <div
        class="{fileCount > 0
          ? 'mt-4 py-3.5'
          : 'mt-6 min-h-[132px] py-6 sm:min-h-[100px]'} flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 text-center transition-[background-color,border-color,scale,min-height,padding,margin] duration-(--duration-quick) ease-[var(--ease-smooth-out)] {dragging
          ? 'border-accent-default bg-accent-dimmer scale-[1.02]'
          : fileCount > 0
            ? 'border-positive-default/30 bg-positive-dimmer/10'
            : 'border-default bg-secondary/5'} {remainingSlots > 0 && !dragging
          ? 'hover:border-accent-default hover:bg-secondary/15'
          : ''} {remainingSlots <= 0 ? 'pointer-events-none opacity-50' : ''}"
        ondragover={onDragOver}
        ondragleave={onDragLeave}
        ondrop={onDrop}
        onclick={onOpenFilePicker}
        role="button"
        tabindex={remainingSlots <= 0 ? -1 : 0}
        aria-label="{m.upload_file()} — {getStepLabel(step)}"
        aria-disabled={remainingSlots <= 0 ? "true" : undefined}
        onkeydown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onOpenFilePicker();
          }
        }}
      >
        {#if isUploading}
          <IconLoadingSpinner class="text-accent-default size-6 animate-spin" />
          <span class="text-secondary text-sm">{m.loading()}</span>
        {:else if fileCount > 0}
          <div class="flex items-center gap-2.5">
            <div
              class="bg-positive-default/10 flex size-8 shrink-0 items-center justify-center rounded-full"
            >
              <IconCheck class="text-positive-stronger size-4" />
            </div>
            <span class="text-sm font-medium">{labels.selectedFiles(fileCount)}</span>
          </div>
          {#if remainingSlots > 0}
            <span class="text-muted text-sm">{labels.runtimeUploadHint}</span>
          {:else}
            <span class="text-muted text-sm">{labels.maxFilesReached}</span>
          {/if}
        {:else}
          <IconUploadCloud class="text-muted size-7" />
          <span class="text-secondary text-sm">{labels.runtimeUploadHint}</span>
        {/if}
      </div>

      {#if acceptedMimetypes.length > 0}
        <details
          bind:open={allowedTypesOpen}
          class="border-default bg-secondary/5 mt-3 rounded-lg border px-3 py-2.5"
        >
          <summary
            class="focus-visible:ring-ring flex min-h-[24px] cursor-pointer list-none items-center gap-1.5 text-sm font-medium focus-visible:ring-2 [&::-webkit-details-marker]:hidden"
          >
            <ChevronRight
              class="text-secondary size-3.5 shrink-0 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {allowedTypesOpen
                ? 'rotate-90'
                : ''}"
              aria-hidden="true"
            />
            {labels.allowedTypesToggle}
          </summary>
          <p class="text-secondary mt-2 max-w-prose text-sm leading-relaxed">
            {friendlyMimeNames(acceptedMimetypes).join(", ")}
          </p>
          <details bind:open={technicalMimeOpen} class="mt-2">
            <summary
              class="text-muted focus-visible:ring-ring flex min-h-[24px] cursor-pointer list-none items-center gap-1.5 text-sm hover:underline focus-visible:ring-2 [&::-webkit-details-marker]:hidden"
            >
              <ChevronRight
                class="size-3.5 shrink-0 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {technicalMimeOpen
                  ? 'rotate-90'
                  : ''}"
                aria-hidden="true"
              />
              {labels.technicalMimeToggle}
            </summary>
            <p
              class="text-muted mt-1.5 max-w-prose text-xs leading-relaxed break-all"
              title={acceptedMimetypes.join(", ")}
            >
              {acceptedMimetypes.join(", ")}
            </p>
          </details>
        </details>
      {/if}

      {#if step.max_files != null}
        <span
          class="mt-2 inline-flex text-sm"
          class:text-accent-stronger={fileCount > 0 && remainingSlots > 0}
          class:text-warning-stronger={remainingSlots <= 0}
          class:text-secondary={fileCount === 0}
        >
          {m.flow_run_files_count({
            current: String(fileCount),
            limit: String(step.max_files)
          })}
        </span>
      {/if}

      {#if skippedMessage}
        <p
          class="border-warning-default/30 bg-warning-dimmer text-warning-stronger mt-3 rounded-md border px-3.5 py-2.5 text-sm"
          role="status"
          aria-live="polite"
        >
          {skippedMessage}
        </p>
      {/if}
    {/snippet}

    {#if recording}
      <!-- While the step records, the upload area folds into one line so the
           recorder and its live text stay in view. -->
      <Collapsible.Root class="mt-3">
        <Collapsible.Trigger
          class="group focus-visible:ring-ring flex min-h-8 items-center gap-1.5 rounded-sm text-sm font-medium outline-none focus-visible:ring-2"
        >
          <ChevronRight
            class="text-secondary size-3.5 shrink-0 group-data-[state=open]:rotate-90 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out)"
            aria-hidden="true"
          />
          {m.recording_upload_file_instead()}
        </Collapsible.Trigger>
        <Collapsible.Content>
          {@render uploadArea()}
        </Collapsible.Content>
      </Collapsible.Root>
    {:else}
      {@render uploadArea()}
    {/if}

    {#if supportsAudioRecording}
      <div class="border-default bg-secondary/5 mt-4 rounded-xl border p-4">
        <div class="mb-3 space-y-1">
          <p class="text-sm font-medium">{m.record_microphone_audio()}</p>
          <p class="text-secondary text-sm">
            {m.record_audio_device()}
          </p>
        </div>

        {#if liveTextAvailable || transcription?.speaker_labels.selectable || transcription?.speaker_labels.required}
          <!-- Settings chosen before recording: quiet, so the record control
               stays the thing to press. -->
          <div class="mb-4 grid gap-x-6 gap-y-3 sm:grid-cols-2">
            {#if liveTextAvailable}
              <Field.Field
                orientation="horizontal"
                class="gap-2.5"
                data-disabled={recorderAudioGraph !== null}
              >
                <Switch
                  id="{uid}-live-text"
                  aria-describedby="{uid}-live-text-help"
                  disabled={recorderAudioGraph !== null}
                  bind:checked={
                    () => launchInputState.liveTextOn, (on) => launchInputState.setLiveTextOn(on)
                  }
                />
                <Field.Content>
                  <Field.Label for="{uid}-live-text" class="text-xs font-medium">
                    {m.live_transcription_toggle()}
                  </Field.Label>
                  <Field.Description
                    id="{uid}-live-text-help"
                    class="text-secondary text-[0.8125rem] leading-[1.6]"
                  >
                    {m.live_transcription_toggle_help()}
                  </Field.Description>
                </Field.Content>
              </Field.Field>
            {/if}
            {#if transcription?.speaker_labels.selectable}
              <Field.Field orientation="horizontal" class="gap-2.5">
                <Switch
                  id="{uid}-speaker-labels"
                  aria-describedby="{uid}-speaker-labels-help"
                  bind:checked={
                    () => speakerLabels === true, (on) => launchInputState.setSpeakerLabels(on)
                  }
                />
                <Field.Content>
                  <Field.Label for="{uid}-speaker-labels" class="text-xs font-medium">
                    {m.speaker_labels_toggle()}
                  </Field.Label>
                  <Field.Description
                    id="{uid}-speaker-labels-help"
                    class="text-secondary text-[0.8125rem] leading-[1.6]"
                  >
                    {launchInputState.speakerLabelsOffForStreaming(transcription)
                      ? m.speaker_labels_off_while_streaming()
                      : m.speaker_labels_help()}
                  </Field.Description>
                </Field.Content>
              </Field.Field>
            {:else if transcription?.speaker_labels.required}
              <p class="text-secondary text-[0.8125rem] leading-[1.6]">
                {m.speaker_labels_required()}
              </p>
            {/if}
          </div>
        {/if}

        <AudioRecorder
          bind:this={recorderRef}
          maxBytes={step.max_file_size_bytes ?? null}
          resetToken={recorderResetToken}
          canStart={canStartRecording}
          {onRecordingDone}
          onRecordingStateChange={onRecordingStateChange ?? (() => {})}
          onAudioGraph={handleAudioGraph}
        />

        {#if liveTextOn && livePreview.stepId === step.step_id}
          <LiveTranscriptPanel status={livePreview.status} pieces={livePreview.pieces} />
        {/if}

        {#if sessionPhase === "reconnecting"}
          <div
            class="border-warning-default/30 bg-warning-dimmer text-warning-stronger mt-3 flex items-center gap-2 rounded-md border px-3.5 py-2.5 text-sm"
            role="status"
            aria-live="polite"
          >
            <IconLoadingSpinner class="size-4 shrink-0 animate-spin" />
            <span>{m.recording_session_reconnecting()}</span>
          </div>
        {:else if sessionPhase === "paused-failed"}
          <Alert.Root
            class="border-negative-default/30 bg-negative-dimmer/70 text-negative-stronger mt-3"
          >
            <Alert.Title>{m.recording_session_paused_title()}</Alert.Title>
            <Alert.Description class="text-negative-stronger/90">
              {m.recording_session_paused_body()}
            </Alert.Description>
            <div class="mt-3 flex flex-wrap gap-2">
              {#if onSessionRetry}
                <Button variant="outline" size="sm" onclick={onSessionRetry}>
                  <IconRefresh data-icon="inline-start" />
                  {m.recording_session_paused_retry()}
                </Button>
              {/if}
              {#if onSessionDismissFailure}
                <Button variant="ghost" size="sm" onclick={onSessionDismissFailure}>
                  {m.recording_session_paused_dismiss()}
                </Button>
              {/if}
            </div>
          </Alert.Root>
        {/if}

        {#if hasFailedRecording}
          <Alert.Root
            class="border-warning-default/30 bg-warning-dimmer/60 text-warning-stronger mt-4"
          >
            <Alert.Title>{m.recording_last_clip_ready()}</Alert.Title>
            <Alert.Description class="text-warning-stronger/90">
              {m.recording_upload_failed_preserved()}
            </Alert.Description>
            <div class="mt-3 flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onclick={onRetryRecordedAudio}>
                <IconRefresh data-icon="inline-start" />
                {labels.retryUpload}
              </Button>
              <Button variant="outline" size="sm" onclick={onDownloadRecordedAudio}>
                <IconDownload data-icon="inline-start" />
                {m.save_as_file()}
              </Button>
              {#if onSaveForLater}
                <Button variant="outline" size="sm" onclick={onSaveForLater}>
                  {m.recording_save_for_later()}
                </Button>
              {/if}
              <Button
                variant="ghost"
                size="sm"
                onclick={onDiscardRecordedAudio}
                disabled={!canDiscardRecording}
                title={canDiscardRecording ? undefined : labels.discardRecordingBusy}
                aria-describedby={canDiscardRecording ? undefined : DISCARD_REASON_ID}
              >
                <IconTrash data-icon="inline-start" />
                {m.discard()}
              </Button>
            </div>
            {#if !canDiscardRecording}
              <p id={DISCARD_REASON_ID} class="mt-2 leading-relaxed">
                {labels.discardRecordingBusy}
              </p>
            {/if}
          </Alert.Root>
        {/if}

        {#if recordingNotice}
          <p
            class="border-warning-default/30 bg-warning-dimmer text-warning-stronger mt-3 rounded-md border px-3.5 py-2.5 text-sm"
            role="status"
            aria-live="polite"
          >
            {recordingNotice}
          </p>
        {/if}
      </div>
    {/if}

    {#if uploadError && !hasFailedRecording}
      <div
        class="border-negative-default/30 bg-negative-dimmer text-negative-stronger mt-3 rounded-md border px-3.5 py-2.5 text-sm"
        role="alert"
        aria-live="assertive"
      >
        <p>
          {uploadError}{getUploadErrorHint(classifyUploadError(uploadError ?? ""))}
        </p>
        <Button
          variant="link"
          size="sm"
          class="text-negative-stronger mt-1 h-auto min-h-6 px-0"
          onclick={onRetryUpload}
        >
          {labels.retryUpload}
        </Button>
      </div>
    {/if}

    {#if supportsAudioRecording && fileCount > 0 && remainingSlots > 0}
      <p class="text-secondary mt-3 text-sm leading-relaxed">
        {m.recording_record_another_hint()}
      </p>
    {/if}

    {#if files.length > 0}
      <div class="mt-3 mb-2 flex flex-col gap-1.5">
        {#each files as file (file.id)}
          <div
            class="group bg-hover-dimmer hover:bg-hover-default flex min-h-[44px] items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors duration-(--duration-quick)"
          >
            <div class="flex min-w-0 flex-col">
              <span class="min-w-0 truncate">{file.name ?? file.id}</span>
              {#if file.size}
                <span class="text-secondary text-xs tabular-nums">{formatBytes(file.size)}</span>
              {/if}
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <!-- Faded icons (60 to 70% of the muted grey) sat under the 3:1
                   floor for controls and had no focus ring. -->
              <Button
                variant="ghost"
                size="icon"
                class="text-secondary hover:text-primary size-10"
                onclick={() => onDownloadUploadedFile(file)}
                aria-label="{m.download_file()} {file.name ?? file.id}"
              >
                <IconDownload class="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                class="text-secondary hover:text-negative-stronger size-10"
                onclick={() => onRemoveFile(file.id)}
                aria-label="{m.delete()} {file.name ?? file.id}"
              >
                <IconXMark class="size-4" />
              </Button>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>
