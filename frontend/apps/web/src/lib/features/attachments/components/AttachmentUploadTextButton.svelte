<script lang="ts">
  import { getAttachmentManager } from "../AttachmentManager";
  import { IconUpload } from "@intric/icons/upload";

  export let multiple: true | undefined = undefined;

  const {
    state: { attachmentRules },
    queueValidUploads
  } = getAttachmentManager();
  import { m } from "$lib/paraglide/messages";

  let fileInput: HTMLInputElement;

  function uploadFiles() {
    if (!fileInput.files) return;

    const errors = queueValidUploads([...fileInput.files]);

    if (errors) {
      alert(errors.join("\n"));
    }

    fileInput.value = "";
  }
</script>

<label
  for="fileInput"
  class="border-default hover:bg-hover-stronger flex h-12 w-full cursor-pointer items-center justify-center gap-2 rounded-lg border"
>
  <IconUpload />
  <span>{m.upload_attachment()}</span>
  <input
    type="file"
    bind:this={fileInput}
    aria-label={m.select_file_to_send()}
    id="fileInput"
    {multiple}
    accept={$attachmentRules.acceptString}
    on:change={uploadFiles}
    class="pointer-events-none absolute h-0 w-0 rounded-lg file:border-none file:bg-transparent file:text-transparent"
  />
</label>
