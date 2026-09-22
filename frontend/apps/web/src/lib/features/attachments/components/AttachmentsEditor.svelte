<!--
    Attachment list of an assistant or app in its editor: shows the attached
    files and running uploads, and uploads new files through its own
    AttachmentManager. With `attachmentMode` set, each file also carries a
    reading mode: placed in the prompt on every turn, or looked up with a tool
    when a question calls for it.
-->
<script lang="ts">
  import { untrack } from "svelte";
  import { IconCancel } from "@eneo/icons/cancel";
  import { IconTrash } from "@eneo/icons/trash";
  import type { UploadedFile, components } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Progress } from "$lib/components/ui/progress/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { m } from "$lib/paraglide/messages";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatFileType } from "$lib/core/formatting/formatFileType";
  import { getEneo } from "$lib/core/Eneo";
  import { initAttachmentManager } from "../AttachmentManager";
  import { getExplicitAttachmentRules } from "../getAttachmentRules";
  import AttachmentDropzone from "./AttachmentDropzone.svelte";
  import AttachmentPreview from "./AttachmentPreview.svelte";
  import UploadedFileIcon from "./UploadedFileIcon.svelte";

  /** An attachment with its optional reading mode (assistant attachments carry one, app attachments do not). */
  type Attachment = UploadedFile & {
    /** `false` sends the file as a signed reference the model opens with a tool; `true` or unset inlines it. */
    inline_text?: boolean;
    /** `false` marks a legacy row without a stored original, which can only be inlined. */
    has_download_reference?: boolean | null;
  };

  type Props = {
    /** The editor's attachments; bind it so uploads and removals reach the editor. */
    attachments: Attachment[];
    /** Read once on mount to build the upload rules. */
    allowedAttachments: components["schemas"]["FileRestrictions"];
    /** Set by this component; bind it and call it after saving or discarding to drop the upload queue. */
    cancelUploadsAndClearQueue?: () => void;
    /** Show the per-file reading mode control; unset for resources whose attachments are always inlined. */
    attachmentMode?: boolean;
  };

  let {
    attachments = $bindable(),
    allowedAttachments,
    cancelUploadsAndClearQueue = $bindable(),
    attachmentMode = false
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
      // New attachments are placed in the prompt until the author opts them into look-up.
      attachments = [...attachments, attachmentMode ? { ...newFile, inline_text: true } : newFile];
    }
  }

  /** Set one attachment's mode; replaces the array so the editor diff picks the change up. */
  function setInlineText(fileId: string, inlineText: boolean) {
    attachments = attachments.map((file) =>
      file.id === fileId ? { ...file, inline_text: inlineText } : file
    );
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

    {#if attachmentMode}
      <!-- Phrased by intent (must-know vs look-up), not mechanism. Only a
           persisted file the backend reports as unreferenceable (a legacy row
           without a stored original) is locked to the prompt. -->
      {@const locked = file.has_download_reference === false}
      <RadioGroup.Root
        value={file.inline_text !== false ? "inline" : "lookup"}
        onValueChange={(mode) => setInlineText(file.id, mode !== "lookup")}
        disabled={locked}
        aria-label={m.attachment_mode_for({ name: file.name })}
        title={locked ? m.attachment_mode_lookup_unavailable() : m.attachment_mode_help()}
        class="flex shrink-0 gap-3 text-sm"
      >
        <Field.Label for={`attachment-mode-${file.id}-inline`} class="font-normal">
          <Field.Field orientation="horizontal">
            <RadioGroup.Item value="inline" id={`attachment-mode-${file.id}-inline`} />
            <span class="whitespace-nowrap">{m.attachment_mode_inline()}</span>
          </Field.Field>
        </Field.Label>
        <Field.Label for={`attachment-mode-${file.id}-lookup`} class="font-normal">
          <Field.Field orientation="horizontal">
            <RadioGroup.Item value="lookup" id={`attachment-mode-${file.id}-lookup`} />
            <span class="whitespace-nowrap">{m.attachment_mode_lookup()}</span>
          </Field.Field>
        </Field.Label>
      </RadioGroup.Root>
    {/if}

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
