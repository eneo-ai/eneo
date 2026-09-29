<!--
    Attachment list of an assistant or app in its editor: shows the attached
    files and running uploads, and uploads new files through its own
    AttachmentManager.
-->
<script lang="ts">
  import { untrack } from "svelte";
  import { IconCancel } from "@eneo/icons/cancel";
  import { IconTrash } from "@eneo/icons/trash";
  import type { UploadedFile, components } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Progress } from "$lib/components/ui/progress/index.js";
  import { m } from "$lib/paraglide/messages";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatFileType } from "$lib/core/formatting/formatFileType";
  import { getEneo } from "$lib/core/Eneo";
  import { initAttachmentManager } from "../AttachmentManager";
  import { getExplicitAttachmentRules } from "../getAttachmentRules";
  import AttachmentDropzone from "./AttachmentDropzone.svelte";
  import AttachmentPreview from "./AttachmentPreview.svelte";
  import UploadedFileIcon from "./UploadedFileIcon.svelte";

  type Props = {
    /** The editor's attachments; bind it so uploads and removals reach the editor. */
    attachments: UploadedFile[];
    /** Read once on mount to build the upload rules. */
    allowedAttachments: components["schemas"]["FileRestrictions"];
    /** Set by this component; bind it and call it after saving or discarding to drop the upload queue. */
    cancelUploadsAndClearQueue?: () => void;
  };

  let {
    attachments = $bindable(),
    allowedAttachments,
    cancelUploadsAndClearQueue = $bindable()
  }: Props = $props();

  const eneo = getEneo();

  const {
    state: { attachments: newAttachments },
    clearUploads
  } = initAttachmentManager({
    eneo,
    options: {
      onFileUploaded,
      rules: getExplicitAttachmentRules(untrack(() => allowedAttachments))
    }
  });

  function onFileUploaded(newFile: UploadedFile) {
    if (!attachments.find((file) => file.id === newFile.id)) {
      attachments = [...attachments, newFile];
    }
  }

  async function removeFile(file: { id: string }) {
    // A file still in the upload queue has not been saved to the resource yet, so no later
    // save would delete it: delete it on the server right away.
    if ($newAttachments.find((attachment) => attachment.fileRef?.id === file.id)) {
      await eneo.files.delete({ fileId: file.id });
    }

    attachments = attachments.filter(({ id }) => id !== file.id);
  }

  cancelUploadsAndClearQueue = () => {
    $newAttachments.forEach((upload) => {
      if (upload.status !== "completed") {
        upload.remove();
      }
    });
    clearUploads();
  };

  const runningUploads = $derived(
    $newAttachments.filter((attachment) => attachment.status !== "completed")
  );
</script>

{#each attachments as file (file.id)}
  <div
    class="border-default bg-primary hover:bg-hover-dimmer flex h-16 items-center gap-3 border-b px-4"
  >
    <UploadedFileIcon {file}></UploadedFileIcon>

    <div class="flex flex-grow items-center justify-between gap-1">
      <AttachmentPreview {file} isTableView={true}>
        {#snippet children({ showFile }: { showFile: () => void })}
          <button onclick={showFile} class="line-clamp-1 cursor-pointer text-left hover:underline">
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
        size="icon"
        aria-label={m.remove_file({ fileName: file.name })}
        onclick={() => {
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

      <Progress
        value={upload.progress}
        class="h-2"
        indicatorClass={upload.progress === 100 ? "bg-positive-default" : undefined}
        aria-label={m.upload_progress_for({ name: upload.file.name })}
      />
    </div>

    <div class="min-w-8">
      <Button
        variant="destructive"
        size="icon"
        aria-label={m.remove_file({ fileName: upload.file.name })}
        onclick={() => upload.remove()}
      >
        <IconCancel />
      </Button>
    </div>
  </div>
{/each}

<div class="h-2"></div>
<AttachmentDropzone multiple></AttachmentDropzone>
