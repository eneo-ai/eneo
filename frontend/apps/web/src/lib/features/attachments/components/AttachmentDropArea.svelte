<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconDropFile } from "@intric/icons/drop-file";
  import { getAttachmentManager } from "../AttachmentManager";

  export let isDragging: boolean;
  export let label = m.drop_files_here_to_upload();
  import { m } from "$lib/paraglide/messages";

  const { queueValidUploads } = getAttachmentManager();

  let handleDragLeave = (event: DragEvent) => {
    event.preventDefault();
    isDragging = false;
  };

  let handleDragOver = (event: DragEvent) => {
    event.preventDefault();
    isDragging = true;
  };

  const handleDrop = (event: DragEvent) => {
    event.preventDefault();
    isDragging = false;
    if (event.dataTransfer && event.dataTransfer.files) {
      uploadFiles(event.dataTransfer.files);
    }
  };

  function uploadFiles(selectedFiles: FileList) {
    const errors = queueValidUploads([...selectedFiles]);

    if (errors) {
      alert(errors.join("\n"));
    }
  }
</script>

<form
  on:dragover={handleDragOver}
  on:drop={handleDrop}
  on:dragleave={handleDragLeave}
  class="absolute inset-0 z-[100] flex items-center justify-center p-4 pl-0"
>
  <div
    class="bg-frosted-glass-primary border-stronger pointer-events-none flex h-full w-full items-center justify-center gap-2 rounded-md border p-4 shadow-xl"
  >
    <div
      class=" border-stronger flex h-full w-full flex-col items-center justify-center gap-4 rounded border-2 border-dashed"
    >
      <IconDropFile size="lg" />
      <p class="text-secondary text-center">{label}</p>
    </div>
  </div>
</form>
