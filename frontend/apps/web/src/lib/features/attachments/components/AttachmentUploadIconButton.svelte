<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconAttachment } from "@intric/icons/attachment";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";

  export let label = m.select_documents_to_attach();
  import { m } from "$lib/paraglide/messages";
  let selectedFiles: FileList;

  const {
    state: { attachmentRules },
    queueValidUploads
  } = getAttachmentManager();

  function uploadFiles() {
    if (!selectedFiles) return;

    const errors = queueValidUploads([...selectedFiles]);

    if (errors) {
      alert(errors.join("\n"));
    }
  }
</script>

<div class="relative flex h-9 items-center overflow-hidden">
  <input
    type="file"
    accept={$attachmentRules.acceptString}
    bind:files={selectedFiles}
    aria-label={label}
    multiple
    id="fileInput"
    on:change={uploadFiles}
    class="pointer-events-none absolute w-0 rounded-lg file:border-none file:bg-transparent file:text-transparent"
  />
  <label
    for="fileInput"
    class="bg-secondary text-primary hover:bg-hover-stronger flex h-9 cursor-pointer items-center justify-center gap-1 rounded-lg pr-2 pl-1"
    ><IconAttachment class="text-primary" />{m.attach_files()}</label
  >
</div>
