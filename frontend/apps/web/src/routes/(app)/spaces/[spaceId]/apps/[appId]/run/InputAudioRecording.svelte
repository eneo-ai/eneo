<script lang="ts">
  import type { AttachmentValidationError } from "$lib/features/attachments/AttachmentManager";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconDownload } from "@eneo/icons/download";
  import { IconInfo } from "@eneo/icons/info";
  import { IconCheck } from "@eneo/icons/check";
  import { Button } from "@eneo/ui";
  import { onDestroy, onMount } from "svelte";
  import { browser } from "$app/environment";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import AudioRecorder from "$lib/features/audio/AudioRecorder.svelte";
  import { buildRecordedAudioFile } from "$lib/features/audio/recordedAudioFile";
  import { downloadRecordedAudioFile } from "$lib/features/audio/downloadRecordedAudioFile";
  import FileSizeValidationPanel from "$lib/features/attachments/components/FileSizeValidationPanel.svelte";
  import dayjs from "dayjs";
  import AttachmentItem from "$lib/features/attachments/components/AttachmentItem.svelte";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { fade } from "svelte/transition";

  export let description: string | undefined = m.record_audio_device();

  const {
    queueValidUploadsDetailed,
    state: { attachments, attachmentRules, isUploading }
  } = getAttachmentManager();

  let audioURL: string | undefined;
  let audioFile: File | undefined;
  let recordingWarning: string | null = null;
  let isRecording = false;
  let maxRecordingBytes: number | null = null;
  let recordingQueued = false;
  let shouldWarnOnNavigate = false;
  let showSuccess = false;
  let validationErrors: AttachmentValidationError[] = [];

  $: maxRecordingBytes = $attachmentRules.maxTotalSize ?? null;
  $: recordingQueued = audioFile
    ? $attachments.some((attachment) => attachment.file === audioFile)
    : false;
  $: shouldWarnOnNavigate = isRecording || (!!audioFile && !recordingQueued) || $isUploading;
  $: if (!audioFile) {
    recordingWarning = null;
    validationErrors = [];
  }

  const beforeUnloadHandler = (event: BeforeUnloadEvent) => {
    if (!shouldWarnOnNavigate) return;
    event.preventDefault();
    event.returnValue = m.recording_unsaved_warning();
  };

  onMount(() => {
    if (!browser) return;
    window.addEventListener("beforeunload", beforeUnloadHandler);
  });

  onDestroy(() => {
    if (!browser) return;
    window.removeEventListener("beforeunload", beforeUnloadHandler);
  });

  async function saveAudioFile() {
    if (!audioFile) {
      toast.error(m.recording_not_found());
      return;
    }

    try {
      await downloadRecordedAudioFile(audioFile);
    } catch (error) {
      console.error("Failed to save recording:", error);
      toast.error(m.recording_save_failed());
    }
  }
</script>

<span class="text-secondary">{description}</span>

{#if audioFile && audioURL}
  {#if recordingWarning}
    <div class="alert-warning">
      <IconInfo class="text-warning-default min-w-5 flex-shrink-0" />
      <span>{recordingWarning}</span>
    </div>
  {/if}

  {#if showSuccess}
    <div class="success-flash" transition:fade={{ duration: 200 }}>
      <IconCheck class="text-positive-default" />
      <span>{m.recording_queued()}</span>
    </div>
  {/if}

  {#if $attachments.length > 0}
    {#each $attachments as attachment (attachment.id)}
      <div class="border-stronger bg-primary w-[60ch] rounded-lg border p-2">
        <div class="flex flex-col">
          <AttachmentItem {attachment}></AttachmentItem>
        </div>
      </div>
    {/each}
  {:else}
    <audio controls src={audioURL} class="border-stronger ml-2 h-12 rounded-full border shadow-sm"
    ></audio>
  {/if}

  <div class="action-row">
    {#if $attachments.length === 0}
      <Button
        variant="primary"
        on:click={() => {
          if (!audioFile) {
            toast.error(m.recording_not_found());
            return;
          }
          const errors = queueValidUploadsDetailed([audioFile]);
          validationErrors = errors ?? [];
          if (errors) {
            return;
          } else {
            showSuccess = true;
            setTimeout(() => (showSuccess = false), 1500);
          }
        }}>{m.use_this_recording()}</Button
      >
    {/if}

    <div class="secondary-actions">
      <Button variant="outlined" on:click={saveAudioFile}><IconDownload />{m.save_as_file()}</Button
      >
      {#if $attachments.length === 0}
        <Button
          variant="destructive"
          padding="icon-leading"
          on:click={() => {
            if (confirm(m.confirm_discard_recording())) {
              audioFile = undefined;
              audioURL = undefined;
              recordingWarning = null;
            }
          }}
        >
          <IconTrash />
          {m.discard()}</Button
        >
      {/if}
    </div>
  </div>

  <FileSizeValidationPanel errors={validationErrors} />
{:else}
  <AudioRecorder
    maxBytes={maxRecordingBytes}
    onRecordingStateChange={(active) => {
      isRecording = active;
    }}
    onRecordingDone={({ blob, mimeType, reason }) => {
      audioFile = buildRecordedAudioFile({
        blob,
        mimeType,
        fileNameBase: m.recording_filename_template({
          datetime: dayjs().format("YYYY-MM-DD HH:mm:ss")
        })
      });
      audioURL = URL.createObjectURL(blob);
      if (reason === "limit") {
        recordingWarning = m.recording_limit_reached();
      } else if (reason === "stall") {
        recordingWarning = m.recording_stalled();
      } else if (reason === "error") {
        recordingWarning = m.recording_saved_after_error();
      } else {
        recordingWarning = null;
      }
    }}
  ></AudioRecorder>
{/if}

<style lang="postcss">
  @reference "@eneo/ui/styles";

  .alert-warning {
    @apply flex items-start gap-3 rounded-lg p-4;
    @apply border-warning-default/30 bg-warning-dimmer text-warning-stronger border;
    @apply text-sm;
    max-width: 60ch;
  }

  .success-flash {
    @apply flex items-center gap-2 rounded-lg p-3;
    @apply bg-positive-dimmer text-positive-stronger;
    max-width: 60ch;
  }

  .action-row {
    @apply flex flex-wrap items-center gap-3;
  }

  .secondary-actions {
    @apply flex items-center gap-2;
  }
</style>
