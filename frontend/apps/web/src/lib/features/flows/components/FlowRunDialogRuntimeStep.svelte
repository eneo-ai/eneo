<script lang="ts">
  import type { FlowRunContractStepInput, UploadedFile } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconUploadCloud } from "@intric/icons/upload-cloud";
  import { IconXMark } from "@intric/icons/x-mark";
  import { IconCheck } from "@intric/icons/check";
  import { IconDownload } from "@intric/icons/download";
  import { IconRefresh } from "@intric/icons/refresh";
  import { IconTrash } from "@intric/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    classifyUploadError,
    getUploadErrorHint,
    friendlyMimeNames
  } from "$lib/features/flows/flowRuntimeErrorMapping";
  import AudioRecorder from "$lib/features/audio/AudioRecorder.svelte";
  import type { RecordingStopReason } from "$lib/features/audio/recordedAudioFile";
  import type { FlowRunBlocker } from "$lib/features/flows/flowRunWizard";
  import type { FlowRunDialogLabels } from "./flowRunDialogLabels";

  let {
    step,
    files,
    recordedFile,
    recorderResetToken,
    fileCount,
    remainingSlots,
    isUploading,
    uploadError,
    recordingNotice,
    skippedMessage,
    blockers,
    dragging,
    labels,
    locale,
    onOpenFilePicker,
    onRemoveFile,
    onDownloadUploadedFile,
    onRetryUpload,
    onDownloadRecordedAudio,
    onRetryRecordedAudio,
    onDiscardRecordedAudio,
    onRecordingDone,
    onRecordingStateChange,
    onDrop,
    onDragOver,
    onDragLeave
  }: {
    step: FlowRunContractStepInput;
    files: UploadedFile[];
    recordedFile: File | null;
    recorderResetToken: number;
    fileCount: number;
    remainingSlots: number;
    isUploading: boolean;
    uploadError: string | null;
    recordingNotice: string | null;
    skippedMessage: string | null;
    blockers: FlowRunBlocker[];
    dragging: boolean;
    labels: FlowRunDialogLabels;
    locale: "sv" | "en";
    onOpenFilePicker: () => void;
    onRemoveFile: (fileId: string) => void;
    onDownloadUploadedFile: (file: UploadedFile) => void;
    onRetryUpload: () => void;
    onDownloadRecordedAudio: () => void;
    onRetryRecordedAudio: () => void;
    onDiscardRecordedAudio: () => void;
    onRecordingDone: (params: {
      blob: Blob;
      mimeType: string;
      reason: RecordingStopReason;
    }) => void;
    onRecordingStateChange?: (isRecording: boolean) => void;
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

  function formatBytes(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  }

  const supportsAudioRecording = $derived(step.input_format === "audio");
</script>

<div class="flex flex-col gap-5">
  <div class="px-1">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="flex flex-wrap items-center gap-2">
          <p class="text-muted text-xs font-medium tracking-[0.14em] uppercase">
            {labels.runtimeStepUploadTitle}
          </p>
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
        <p class="text-muted mt-2 text-sm leading-relaxed">
          {labels.runtimeScopeHint(step.step_order)}
        </p>
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
            Max {formatBytes(step.max_file_size_bytes)}/{locale === "sv" ? "fil" : "file"}
          </span>
        {/if}
      </div>
    </div>

    {#if blockers.length > 0}
      <div
        class="border-accent-default/20 bg-accent-dimmer/30 text-accent-stronger mt-5 rounded-lg border px-3.5 py-2.5 text-sm"
        role="status"
        aria-live="polite"
      >
        {blockers[0]?.title}
      </div>
    {/if}

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

    <div
      class="{fileCount > 0
        ? 'mt-4 py-3.5'
        : 'mt-6 min-h-[132px] py-6 sm:min-h-[100px]'} flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 text-center transition-all duration-150 {dragging
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
            <IconCheck class="text-positive-default size-4" />
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
        <span class="text-secondary text-sm">{m.upload_file()}</span>
        <span class="text-muted text-sm">{labels.runtimeUploadHint}</span>
      {/if}
    </div>

    {#if step.accepted_mimetypes.length > 0}
      <details class="border-default bg-secondary/5 mt-3 rounded-lg border px-3 py-2.5">
        <summary class="cursor-pointer text-sm font-medium">
          {labels.allowedTypesToggle}
        </summary>
        <p class="text-secondary mt-2 max-w-prose text-sm leading-relaxed">
          {friendlyMimeNames(step.accepted_mimetypes).join(", ")}
        </p>
        <details class="mt-2">
          <summary class="text-muted cursor-pointer text-sm hover:underline">
            {labels.technicalMimeToggle}
          </summary>
          <p
            class="text-muted mt-1.5 max-w-prose text-xs leading-relaxed break-all"
            title={step.accepted_mimetypes.join(", ")}
          >
            {step.accepted_mimetypes.join(", ")}
          </p>
        </details>
      </details>
    {/if}

    {#if step.max_files != null}
      <span
        class="mt-2 inline-flex text-sm"
        class:text-accent-stronger={fileCount > 0 && remainingSlots > 0}
        class:text-warning-stronger={remainingSlots <= 0}
        class:text-muted={fileCount === 0}
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

    {#if supportsAudioRecording}
      <div class="border-default bg-secondary/5 mt-4 rounded-xl border p-4">
        <div class="mb-3 space-y-1">
          <p class="text-sm font-medium">{m.record_microphone_audio()}</p>
          <p class="text-muted text-sm">
            {m.record_audio_device()}
          </p>
        </div>

        <AudioRecorder
          maxBytes={step.max_file_size_bytes ?? null}
          resetToken={recorderResetToken}
          {onRecordingDone}
          onRecordingStateChange={onRecordingStateChange ?? (() => {})}
        />

        {#if recordedFile && uploadError}
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
              <Button variant="ghost" size="sm" onclick={onDiscardRecordedAudio}>
                <IconTrash data-icon="inline-start" />
                {m.discard()}
              </Button>
            </div>
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

    {#if uploadError && !recordedFile}
      <div
        class="border-negative-default/30 bg-negative-dimmer text-negative-stronger mt-3 rounded-md border px-3.5 py-2.5 text-sm"
        role="alert"
        aria-live="assertive"
      >
        <p>
          {uploadError}{getUploadErrorHint(classifyUploadError(uploadError ?? ""))}
        </p>
        <button
          class="text-negative-stronger mt-1.5 text-xs font-medium underline underline-offset-2 hover:no-underline"
          onclick={onRetryUpload}
        >
          {labels.retryUpload}
        </button>
      </div>
    {/if}

    {#if supportsAudioRecording && fileCount > 0 && remainingSlots > 0}
      <p class="text-muted mt-3 text-sm leading-relaxed">
        {m.recording_record_another_hint()}
      </p>
    {/if}

    {#if files.length > 0}
      <div class="mt-3 mb-2 flex flex-col gap-1.5">
        {#each files as file (file.id)}
          <div
            class="group bg-hover-dimmer hover:bg-hover-default flex min-h-[44px] items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors duration-100"
          >
            <div class="flex min-w-0 flex-col">
              <span class="min-w-0 truncate">{file.name ?? file.id}</span>
              {#if file.size}
                <span class="text-muted text-xs">{formatBytes(file.size)}</span>
              {/if}
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <button
                class="text-muted/70 hover:text-accent-stronger group-hover:text-muted flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md transition-colors duration-100"
                onclick={() => onDownloadUploadedFile(file)}
                aria-label="{m.download_file()} {file.name ?? file.id}"
              >
                <IconDownload class="size-4" />
              </button>
              <button
                class="text-muted/60 hover:text-negative-default group-hover:text-muted flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md transition-colors duration-100"
                onclick={() => onRemoveFile(file.id)}
                aria-label="{m.delete()} {file.name ?? file.id}"
              >
                <IconXMark class="size-4" />
              </button>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>
