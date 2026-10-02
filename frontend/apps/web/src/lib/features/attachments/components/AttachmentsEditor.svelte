<!--
    Attachment list of an assistant or app in its editor: shows the attached
    files and running uploads, and uploads new files through its own
    AttachmentManager. With `attachmentMode` set, each file also carries a
    reading mode: loaded before every answer, or opened on demand with a tool
    when a question calls for it.
-->
<script lang="ts">
  import { tick, untrack } from "svelte";
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

  /** What decides whether a file can be opened on demand: the installation and the model that answers. */
  type AttachmentMode = {
    fileReferencesEnabled: boolean;
    selectedModel?: { id: string; supports_tool_calling?: boolean };
  };

  type Props = {
    /** The editor's attachments; bind it so uploads and removals reach the editor. */
    attachments: Attachment[];
    /** Read once on mount to build the upload rules. */
    allowedAttachments: components["schemas"]["FileRestrictions"];
    /** Set by this component; bind it and call it after saving or discarding to drop the upload queue. */
    cancelUploadsAndClearQueue?: () => void;
    /** Show the per-file reading mode; unset for resources whose attachments are always inlined. */
    attachmentMode?: AttachmentMode;
  };

  let {
    attachments = $bindable(),
    allowedAttachments,
    cancelUploadsAndClearQueue = $bindable(),
    attachmentMode
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

  let editingFileId = $state<string | null>(null);

  /** Why a file cannot be opened on demand right now, or null when it can. */
  function lookupUnavailable(file: Attachment): string | null {
    if (!attachmentMode) return null;
    if (
      file.mimetype.startsWith("image/") ||
      file.mimetype.startsWith("audio/") ||
      file.mimetype.startsWith("video/")
    )
      return m.material_file_type_inline();
    if (file.has_download_reference === false) return m.attachment_mode_lookup_unavailable();
    if (!attachmentMode.fileReferencesEnabled) return m.material_file_references_unavailable();
    if (!attachmentMode.selectedModel) return m.material_select_model();
    if (!attachmentMode.selectedModel.supports_tool_calling)
      return m.material_file_model_fallback();
    return null;
  }

  function onFileUploaded(newFile: UploadedFile) {
    if (!attachments.find((file) => file.id === newFile.id)) {
      // New attachments open on demand; unavailable tool access falls back to inline content.
      attachments = [...attachments, attachmentMode ? { ...newFile, inline_text: false } : newFile];
    }
  }

  /** Set one attachment's mode; replaces the array so the editor diff picks the change up. */
  async function setInlineText(fileId: string, inlineText: boolean) {
    const file = attachments.find((attachment) => attachment.id === fileId);
    if (!file || (file.inline_text !== false) === inlineText) return;
    if (!inlineText && lookupUnavailable(file)) return;
    attachments = attachments.map((attachment) =>
      attachment.id === fileId ? { ...attachment, inline_text: inlineText } : attachment
    );
    editingFileId = null;
    // Return focus to the file action after closing its options.
    await tick();
    document.getElementById("attachment-mode-" + fileId)?.focus();
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

{#snippet fileRow(file: Attachment)}
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
{/snippet}

{#snippet modeRow(file: Attachment)}
  {@const unavailable = lookupUnavailable(file)}
  {@const inline = file.inline_text !== false || unavailable !== null}
  <div class="border-default border-b">
    <div class="flex min-h-16 items-center gap-3 py-3">
      <UploadedFileIcon {file} class="shrink-0" />
      <div class="min-w-0 flex-1">
        <AttachmentPreview {file} isTableView={true}>
          {#snippet children({ showFile }: { showFile: () => void })}
            <button
              onclick={showFile}
              class="w-full cursor-pointer truncate text-left hover:underline"
            >
              {file.name}
            </button>
          {/snippet}
        </AttachmentPreview>
        <p class="text-secondary mt-1 text-sm">
          {formatFileType(file.mimetype)} · {formatBytes(file.size)}
        </p>
        <p class="text-secondary text-sm">
          {inline ? m.material_file_inline_status() : m.material_file_lookup_status()}
        </p>
        {#if file.inline_text === false && unavailable}
          <p class="text-warning-stronger mt-1 text-sm">{unavailable}</p>
        {/if}
      </div>
      <button
        id={"attachment-mode-" + file.id}
        type="button"
        class="border-default hover:bg-hover-dimmer shrink-0 rounded-lg border px-3 py-1.5 text-sm"
        aria-label={m.material_change_file({ name: file.name })}
        aria-expanded={editingFileId === file.id}
        aria-controls={"attachment-options-" + file.id}
        onclick={() => (editingFileId = editingFileId === file.id ? null : file.id)}
        >{m.material_change()}</button
      >
      <Button
        variant="destructive"
        size="icon"
        aria-label={m.material_remove_file({ name: file.name })}
        onclick={() => removeFile(file)}
      >
        <IconTrash></IconTrash>
      </Button>
    </div>
    <div
      id={"attachment-options-" + file.id}
      hidden={editingFileId !== file.id}
      class="bg-secondary mb-3 rounded-lg p-3"
    >
      <RadioGroup.Root
        value={file.inline_text === false ? "lookup" : "inline"}
        onValueChange={(mode) => setInlineText(file.id, mode !== "lookup")}
        aria-label={m.material_change_file({ name: file.name })}
        aria-describedby={"attachment-help-" + file.id}
        class="grid grid-cols-2 gap-2"
      >
        <Field.Label for={"attachment-mode-" + file.id + "-lookup"} class="font-normal">
          <Field.Field orientation="horizontal">
            <RadioGroup.Item
              value="lookup"
              id={"attachment-mode-" + file.id + "-lookup"}
              disabled={unavailable !== null && file.inline_text !== false}
            />
            <span>{m.material_open_when_needed()}</span>
          </Field.Field>
        </Field.Label>
        <Field.Label for={"attachment-mode-" + file.id + "-inline"} class="font-normal">
          <Field.Field orientation="horizontal">
            <RadioGroup.Item value="inline" id={"attachment-mode-" + file.id + "-inline"} />
            <span>{m.material_file_always_option()}</span>
          </Field.Field>
        </Field.Label>
      </RadioGroup.Root>
      <p id={"attachment-help-" + file.id} class="text-secondary mt-2 text-sm">
        {m.attachment_mode_help()}
      </p>
      {#if unavailable}
        <p class="text-warning-stronger mt-2 text-sm">{unavailable}</p>
      {/if}
    </div>
  </div>
{/snippet}

{#each attachments as file (file.id)}
  {#if attachmentMode}
    {@render modeRow(file)}
  {:else}
    {@render fileRow(file)}
  {/if}
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
<AttachmentDropzone multiple description={attachmentMode ? m.material_new_files_hint() : undefined}
></AttachmentDropzone>
