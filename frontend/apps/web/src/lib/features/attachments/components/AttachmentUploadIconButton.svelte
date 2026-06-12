<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Paperclip } from "lucide-svelte";
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { m } from "$lib/paraglide/messages";

  export let label = m.select_documents_to_attach();
  let fileInput: HTMLInputElement;

  const {
    state: { attachmentRules },
    queueValidUploads
  } = getAttachmentManager();

  function uploadFiles() {
    if (!fileInput.files?.length) return;

    queueValidUploads([...fileInput.files]);
    // Reset so re-selecting the same file still fires `change`.
    fileInput.value = "";
  }
</script>

<label
  class={buttonVariants({ variant: "ghost", size: "icon" }) + " size-9 cursor-pointer rounded-lg"}
  title={label}
  aria-label={label}
>
  <Paperclip class="size-5" />
  <input
    type="file"
    accept={$attachmentRules.acceptString}
    bind:this={fileInput}
    multiple
    on:change={uploadFiles}
    class="sr-only"
  />
</label>
