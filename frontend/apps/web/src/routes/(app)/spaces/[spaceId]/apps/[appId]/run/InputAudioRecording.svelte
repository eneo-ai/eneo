<script lang="ts">
  import { IconTrash } from "@intric/icons/trash";
  import { IconDownload } from "@intric/icons/download";
  import { Button } from "@intric/ui";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import dayjs from "dayjs";
  import AudioRecorder from "./AudioRecorder.svelte";
  import AttachmentItem from "$lib/features/attachments/components/AttachmentItem.svelte";
  import { m } from "$lib/paraglide/messages";

  export let description = m.record_audio_device();

  const {
    queueValidUploads,
    state: { attachments }
  } = getAttachmentManager();

  let audioURL: string | undefined;
  let audioFile: File | undefined;

  async function saveAudioFile() {
    if (!audioFile) {
      alert(m.recording_not_found());
      return;
    }
    const suggestedName = audioFile.name + (audioFile.type.includes("webm") ? ".webm" : ".mp4");
    if (window.showSaveFilePicker) {
      const handle = await window.showSaveFilePicker({ suggestedName });
      const writable = await handle.createWritable();
      await writable.write(audioFile);
      writable.close();
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

    <div class="flex items-center gap-4">
      <Button
        variant="destructive"
        padding="icon-leading"
        on:click={() => {
          if (confirm(m.confirm_discard_recording())) {
            audioFile = undefined;
            audioURL = undefined;
          }
        }}
      >
        <IconTrash />
        {m.discard()}</Button
      >
      <Button variant="outlined" on:click={saveAudioFile}><IconDownload />{m.save_as_file()}</Button>
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
    </div>
  {/if}
{:else}
  <AudioRecorder
    onRecordingDone={({ blob, mimeType }) => {
      const extension = mimeType.replaceAll("audio/", "").split(";")[0] ?? "";
      const fileName = `${m.recording_filename_template({ datetime: dayjs().format("YYYY-MM-DD HH:mm:ss") })}.${extension}`;
      audioFile = new File([blob], fileName, { type: mimeType });
      audioURL = URL.createObjectURL(blob);
    }}
  ></AudioRecorder>
{/if}
