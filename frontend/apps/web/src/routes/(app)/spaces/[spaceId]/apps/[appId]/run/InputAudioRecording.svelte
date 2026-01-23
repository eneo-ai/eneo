<script lang="ts">
  import { IconTrash } from "@intric/icons/trash";
  import { IconDownload } from "@intric/icons/download";
  import { Button } from "@intric/ui";
  import { onDestroy, onMount } from "svelte";
  import { browser } from "$app/environment";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import dayjs from "dayjs";
  import AudioRecorder from "./AudioRecorder.svelte";
  import AttachmentItem from "$lib/features/attachments/components/AttachmentItem.svelte";
  import { m } from "$lib/paraglide/messages";

  export let description = m.record_audio_device();

  const {
    queueValidUploads,
    state: { attachments, attachmentRules, isUploading }
  } = getAttachmentManager();

  let audioURL: string | undefined;
  let audioFile: File | undefined;
  let recordingWarning: string | null = null;
  let isRecording = false;
  let maxRecordingBytes: number | null = null;
  let recordingQueued = false;
  let shouldWarnOnNavigate = false;

  $: maxRecordingBytes = $attachmentRules.maxTotalSize ?? null;
  $: recordingQueued = audioFile
    ? $attachments.some((attachment) => attachment.file === audioFile)
    : false;
  $: shouldWarnOnNavigate =
    isRecording || (!!audioFile && !recordingQueued) || $isUploading;
  $: if (!audioFile) {
    recordingWarning = null;
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
      alert(m.recording_not_found());
      return;
    }
    const suggestedName = audioFile.name + (audioFile.type.includes("webm") ? ".webm" : ".mp4");
    if (window.showSaveFilePicker) {
      try {
        const handle = await window.showSaveFilePicker({ suggestedName });
        const writable = await handle.createWritable();
        await writable.write(audioFile);
        await writable.close();
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        console.error("Failed to save recording:", error);
        alert(m.recording_save_failed());
      }
    } else {
      const a = document.createElement("a");
      a.download = suggestedName;
      a.href = URL.createObjectURL(audioFile);
      a.click();
      setTimeout(function () {
        URL.revokeObjectURL(a.href);
      }, 1500);
    }
  }
</script>

<span class="text-secondary">{description}</span>

{#if audioFile && audioURL}
  {#if recordingWarning}
    <div
      class="border-warning-default/40 bg-warning-dimmer text-warning-default w-[60ch] rounded-lg border p-3 text-sm"
    >
      {recordingWarning}
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

  <div class="flex items-center gap-4">
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
    <Button variant="outlined" on:click={saveAudioFile}><IconDownload />{m.save_as_file()}</Button>
    {#if $attachments.length === 0}
      <Button
        variant="primary"
        on:click={() => {
          if (!audioFile) {
            alert(m.recording_not_found());
            return;
          }
          const errors = queueValidUploads([audioFile]);
          if (errors) {
            alert(errors);
          }
        }}>{m.use_this_recording()}</Button
      >
    {/if}
  </div>
{:else}
  <AudioRecorder
    maxBytes={maxRecordingBytes}
    onRecordingStateChange={(active) => {
      isRecording = active;
    }}
    onRecordingDone={({ blob, mimeType, reason }) => {
      const extension = mimeType.replaceAll("audio/", "").split(";")[0] ?? "";
      const fileName = `${m.recording_filename_template({ datetime: dayjs().format("YYYY-MM-DD HH:mm:ss") })}.${extension}`;
      audioFile = new File([blob], fileName, { type: mimeType });
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
