<script lang="ts">
  import { IconCancel } from "@intric/icons/cancel";
  import { IconTrash } from "@intric/icons/trash";
  import { Button, ProgressBar } from "@intric/ui";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatFileType } from "$lib/core/formatting/formatFileType";
  import { getIntric } from "$lib/core/Intric";
  import { getAppEditor } from "$lib/features/apps/AppEditor";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import AttachmentUploadTextButton from "$lib/features/attachments/components/AttachmentUploadTextButton.svelte";
  import { getExplicitAttachmentRules } from "$lib/features/attachments/getAttachmentRules";
  import type { UploadedFile } from "@intric/intric-js";
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import AttachmentPreview from "$lib/features/attachments/components/AttachmentPreview.svelte";

  // This is only the new uploads, it is bound to the attachment upload
  const intric = getIntric();
  const {
    state: { update }
  } = getAppEditor();

  const attachmentRules = getExplicitAttachmentRules($update.allowed_attachments);

  const {
    state: { attachments: newAttachments },
    clearUploads
  } = initAttachmentManager({ intric, options: { onFileUploaded, rules: attachmentRules } });

  function onFileUploaded(newFile: UploadedFile) {
    // After successful upload add the uploaded file ref to attachments
    if (!$update.attachments.find((file) => file.id === newFile.id)) {
      $update.attachments = [...$update.attachments, newFile];
    }
  }

  async function removeFile(file: { id: string }) {
    // If this file is still in the attachments it means it has not yet been saved in the service
    // This means we will delete it right away on the server as there is no later action to defer to
    if (
      $newAttachments.find((attachment) => attachment.fileRef && attachment.fileRef.id === file.id)
    ) {
      await intric.files.delete({ fileId: file.id });
    }

    $update.attachments = $update.attachments.toSpliced(
      $update.attachments.findIndex(({ id }) => id === file.id),
      1
    );
  }

  /**
   * Reset the upload queue. Use after saving the app.
   * */
  export function cancelUploadsAndClearQueue() {
    $newAttachments.forEach((upload) => {
      if (upload.status !== "completed") {
        upload.remove();
      }
      clearUploads();
    });
  }

  $: runningUploads = $newAttachments.filter((attachment) => attachment.status !== "completed");
</script>

{#each $update.attachments as file (file.id)}
  <div
    class="border-default bg-primary hover:bg-hover-dimmer flex h-16 items-center gap-3 border-b px-4"
  >
    <UploadedFileIcon {file}></UploadedFileIcon>

    <div class="flex flex-grow items-center justify-between gap-1">
      <AttachmentPreview {file} isTableView={true}>
        {#snippet children({ showFile }: { showFile: () => void })}
          <button
            on:click={showFile}
            class="line-clamp-1 cursor-pointer text-left hover:underline"
          >
            {file.name}
          </button>
        {/snippet}
      </AttachmentPreview>
      <span class="text-secondary line-clamp-1 text-right text-sm">
        {formatFileType(file.mimetype)} · {formatBytes(file.size)}
      </span>
    </div>

    <div class="min-w-8">
      <Button
        variant="destructive"
        padding="icon"
        on:click={() => {
          removeFile(file);
        }}
      >
        <IconTrash></IconTrash>
      </Button>
    </div>
  </div>
{/each}

{#each runningUploads as upload (upload.id)}
  <div
    class="border-default bg-primary hover:bg-hover-dimmer flex h-16 w-full items-center gap-4 border-b px-4"
  >
    <UploadedFileIcon file={{ mimetype: upload.file.type }}></UploadedFileIcon>

    <div class="flex flex-grow flex-col gap-1">
      <div class="flex max-w-full items-center gap-4">
        <span class="line-clamp-1 flex-grow font-medium">
          {upload.file.name}
        </span>
        <span class="text-secondary line-clamp-1 text-right text-sm">
          {formatFileType(upload.file.type)} · {formatBytes(upload.file.size)}
        </span>
      </div>

      <ProgressBar progress={upload.progress}></ProgressBar>
    </div>

    <div class="min-w-8">
      <Button variant="destructive" padding="icon" on:click={() => upload.remove()}>
        <IconCancel />
      </Button>
    </div>
  </div>
{/each}

<div class="h-2"></div>
<AttachmentUploadTextButton multiple></AttachmentUploadTextButton>
