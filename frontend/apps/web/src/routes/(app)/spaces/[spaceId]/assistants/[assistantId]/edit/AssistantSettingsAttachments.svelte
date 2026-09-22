<script lang="ts">
  import { IconCancel } from "@eneo/icons/cancel";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button, Input, ProgressBar } from "@eneo/ui";
  import { tick } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatFileType } from "$lib/core/formatting/formatFileType";
  import { getEneo } from "$lib/core/Eneo";
  import { getAssistantEditor } from "$lib/features/assistants/AssistantEditor";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import AttachmentDropzone from "$lib/features/attachments/components/AttachmentDropzone.svelte";
  import { getExplicitAttachmentRules } from "$lib/features/attachments/getAttachmentRules";
  import type { UploadedFile, components } from "@eneo/eneo-js";
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import AttachmentPreview from "$lib/features/attachments/components/AttachmentPreview.svelte";
  import ConfigContextMeter from "$lib/features/assistants/components/ConfigContextMeter.svelte";
  type Attachment = components["schemas"]["AssistantAttachmentPublic"];
  type Props = {
    fileReferencesEnabled: boolean;
    selectedModel?: { id: string; max_input_tokens: number; supports_tool_calling?: boolean };
  };
  let { fileReferencesEnabled, selectedModel }: Props = $props();
  let editingFileId = $state<string | null>(null);

  function lookupUnavailable(file: Attachment): string | null {
    if (
      file.mimetype.startsWith("image/") ||
      file.mimetype.startsWith("audio/") ||
      file.mimetype.startsWith("video/")
    )
      return m.material_file_type_inline();
    if (file.has_download_reference === false) return m.attachment_mode_lookup_unavailable();
    if (!fileReferencesEnabled) return m.material_file_references_unavailable();
    if (!selectedModel) return m.material_select_model();
    if (!selectedModel.supports_tool_calling) return m.material_file_model_fallback();
    return null;
  }

  // This is only the new uploads, it is bound to the attachment upload
  const eneo = getEneo();
  const {
    state: { update, resource }
  } = getAssistantEditor();
  const attachmentRules = getExplicitAttachmentRules($update.allowed_attachments);

  const {
    state: { attachments: newAttachments },
    clearUploads
  } = initAttachmentManager({ eneo, options: { onFileUploaded, rules: attachmentRules } });

  function onFileUploaded(newFile: UploadedFile) {
    // After successful upload add the uploaded file ref to attachments.
    // New attachments open on demand; unavailable tool access falls back to inline content.
    if (!$update.attachments.find((file) => file.id === newFile.id)) {
      $update.attachments = [...$update.attachments, { ...newFile, inline_text: false }];
    }
  }

  async function setInlineText(fileId: string, inlineText: boolean) {
    const file = $update.attachments.find((attachment) => attachment.id === fileId);
    if (!file || (file.inline_text !== false) === inlineText) return;
    if (!inlineText && lookupUnavailable(file)) return;
    $update.attachments = $update.attachments.map((file) =>
      file.id === fileId ? { ...file, inline_text: inlineText } : file
    );
    editingFileId = null;
    // Return focus to the file action after closing its options.
    await tick();
    document.getElementById("attachment-mode-" + fileId)?.focus();
  }

  async function removeFile(file: { id: string }) {
    // If this file is still in the attachments it means it has not yet been saved in the service
    // This means we will delete it right away on the server as there is no later action to defer to
    if (
      $newAttachments.find((attachment) => attachment.fileRef && attachment.fileRef.id === file.id)
    ) {
      await eneo.files.delete({ fileId: file.id });
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

  const runningUploads = $derived(
    $newAttachments.filter((attachment) => attachment.status !== "completed")
  );
</script>

<ConfigContextMeter
  assistantId={$resource.id}
  model={selectedModel}
  prompt={$update.prompt.text}
  attachments={$update.attachments}
></ConfigContextMeter>

{#snippet attachmentRow(file: Attachment)}
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
        padding="icon"
        aria-label={m.material_remove_file({ name: file.name })}
        on:click={() => removeFile(file)}><IconTrash /></Button
      >
    </div>
    <div
      id={"attachment-options-" + file.id}
      hidden={editingFileId !== file.id}
      class="bg-secondary mb-3 rounded-lg p-3"
    >
      <div
        role="radiogroup"
        aria-label={m.material_change_file({ name: file.name })}
        aria-describedby={"attachment-help-" + file.id}
      >
        <Input.RadioSwitch
          bind:value={() => file.inline_text === false, (on) => setInlineText(file.id, !on)}
          disabled={unavailable !== null && file.inline_text !== false}
          labelTrue={m.material_open_when_needed()}
          labelFalse={m.material_file_always_option()}
        />
      </div>
      <p id={"attachment-help-" + file.id} class="text-secondary mt-2 text-sm">
        {m.attachment_mode_help()}
      </p>
      {#if unavailable}
        <p class="text-warning-stronger mt-2 text-sm">{unavailable}</p>
      {/if}
    </div>
  </div>
{/snippet}

<section aria-labelledby="material-attachments-heading">
  <h4 id="material-attachments-heading" class="font-medium">{m.attachments()}</h4>
  <p class="text-secondary mt-1 mb-3 text-sm">{m.material_attachments_description()}</p>

  {#each $update.attachments as file (file.id)}
    {@render attachmentRow(file)}
  {/each}

  <div class="mt-4">
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
          <Button
            variant="destructive"
            padding="icon"
            aria-label={m.cancel()}
            on:click={() => upload.remove()}
          >
            <IconCancel />
          </Button>
        </div>
      </div>
    {/each}

    <div class="h-2"></div>
    <AttachmentDropzone multiple description={m.material_new_files_hint()} />
  </div>
</section>
