<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconAttachment } from "@intric/icons/attachment";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";

  export let label = m.select_documents_to_attach();
  export let disabled = false;
  import { m } from "$lib/paraglide/messages";
  let selectedFiles: FileList;
  let fileInput: HTMLInputElement;

  const {
    state: { attachmentRules },
    queueValidUploads
  } = getAttachmentManager();

  function uploadFiles() {
    if (disabled) return;
    if (!selectedFiles) return;

    const errors = queueValidUploads([...selectedFiles]);

    if (errors) {
      alert(errors.join("\n"));
    }

    // Reset the input so the same file can be selected again
    if (fileInput) {
      fileInput.value = '';
    }
  }

  function handleInputClick(e: MouseEvent) {
    if (disabled) {
      e.preventDefault();
      e.stopPropagation();
    }
  }
</script>

<div class="relative flex h-9 items-center overflow-hidden">
  <input
    bind:this={fileInput}
    type="file"
    accept={$attachmentRules.acceptString}
    bind:files={selectedFiles}
    aria-label={label}
    multiple
    id="fileInput"
    on:click={handleInputClick}
    on:change={uploadFiles}
    {disabled}
    class="pointer-events-none absolute w-0 rounded-lg file:border-none file:bg-transparent file:text-transparent"
  />
  <label
    for="fileInput"
    class="bg-secondary text-primary flex h-9 items-center justify-center gap-1 rounded-lg pr-2 pl-1 {disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:bg-hover-stronger'}"
    ><IconAttachment class="text-primary" />{m.attach_files()}</label
  >
</div>
