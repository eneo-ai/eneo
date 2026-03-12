<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import type { FileSystemEntry, FileSystemDirectoryEntry, FileSystemFileEntry } from "./types.js";
  import { Button } from "$lib/Button/index.js";
  import { IconFile } from "@intric/icons/file";
  import { IconTrash } from "@intric/icons/trash";
  import { IconUploadCloud } from "@intric/icons/upload-cloud";
  import { IconDropFile } from "@intric/icons/drop-file";

  /** Name of the file input field, defaults to `dropzoneInput` */
  export let name = "dropzoneInput";
  export let acceptedMimeTypes = ["text/plain"];
  export let files: File[] = [];

  let dropzone: HTMLDivElement;
  let dropzoneInput: HTMLInputElement;
  let isDragging = false;

  const dispatch = createEventDispatcher();

  function addFocusDecoration() {
    dropzone.classList.add("focused");
  }

  function removeFocusDecoration() {
    dropzone.classList.remove("focused");
  }

  function handleDragOver(event: DragEvent) {
    addFocusDecoration();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = "copy";
    }
  }

  function handleDragLeave(event: DragEvent) {
    const target = (event.relatedTarget as HTMLElement) ?? null;

    // If drag has ended or left dropzone remove focus deco
    // This event also fires when dragging over other elements inside the dropzone
    if (event.type === "dragend" || !target.classList.contains("dropzone")) {
      removeFocusDecoration();
    }
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    if (event.dataTransfer) {
      removeFocusDecoration();
      const items = event.dataTransfer.items;
      for (let i = 0; i < items.length; i++) {
        let entry = items[i].webkitGetAsEntry();
        scanEntry(entry);
      }
    }
  }

  function scanEntry(entry: FileSystemEntry | null) {
    if (entry) {
      if (entry.isFile) {
        (entry as FileSystemFileEntry).file((file) => addFiles([file]));
      } else if (entry.isDirectory) {
        const reader = (entry as FileSystemDirectoryEntry).createReader();
        reader.readEntries((entries) => {
          entries.forEach((entry) => scanEntry(entry));
        });
      }
    }
  }

  function handleClick() {
    dropzoneInput.click();
  }

  function handleInputChange() {
    addFiles([...(dropzoneInput.files ?? [])]);
  }

  function addFiles(newFiles: File[]) {
    const acceptedFiles: File[] = [];
    const rejectedFiles: File[] = [];

    // Simple check for format: we match file extension
    const fileTypeIsValid = (file: File) => acceptedMimeTypes.includes(file.type);

    // Simple check for duplicates: compare file name, size, and last edited
    const fileIsNotDuplicate = (file: File) =>
      files.find(
        (f) => f.name === file.name && f.size === file.size && f.lastModified === file.lastModified
      ) === undefined;

    for (const file of newFiles) {
      if (fileTypeIsValid(file) && fileIsNotDuplicate(file)) {
        acceptedFiles.push(file);
      } else {
        rejectedFiles.push(file);
      }
    }

    files = [...files, ...acceptedFiles];
    dispatch("fileselectionchanged", { files, rejectedFiles });
  }

  function removeFile(file: File) {
    files = files.filter((f) => f !== file);
    dispatch("fileselectionchanged", { files });
  }

  function handleGlobalDrag(e: DragEvent, state: { isDragging: boolean }) {
    e.preventDefault();
    isDragging = state.isDragging;
  }
</script>

<svelte:window
  on:drop={(e) => {
    handleGlobalDrag(e, { isDragging: false });
  }}
  on:dragover={(e) => {
    handleGlobalDrag(e, { isDragging: true });
  }}
  on:dragend={(e) => {
    handleGlobalDrag(e, { isDragging: false });
  }}
  on:dragleave={(e) => {
    // Only handle leave if leaving window
    if (e.relatedTarget == null) {
      handleGlobalDrag(e, { isDragging: false });
    }
  }}
/>

<div
  class="border-stronger bg-primary relative flex h-full max-h-[80vh] min-h-[50vh] w-full min-w-[200px] flex-col gap-2 overflow-y-auto rounded-lg border p-2 shadow-md"
  bind:this={dropzone}
  on:dragenter={handleDragOver}
  on:dragover={handleDragOver}
  on:dragleave={handleDragLeave}
  on:dragend={handleDragLeave}
  on:drop={handleDrop}
  role="button"
  tabindex="0"
>
  {#if files.length > 0}
    {#each files as file (file)}
      <div
        class="border-default hover:bg-hover-dimmer flex cursor-default items-center justify-between rounded-md border p-2"
      >
        <div class="flex items-center gap-2">
          <IconFile />
          {file.name}
        </div>
        <Button on:click={() => removeFile(file)} destructive padding="icon">
          <IconTrash />
        </Button>
      </div>
    {/each}
  {:else}
    <button
      class="hover:bg-hover-dimmer absolute inset-0 rounded-lg"
      on:click={handleClick}
      tabindex="0"
      aria-labelledby="upload-notice"
    >
    </button>
    <div
      class="text-primary pointer-events-none absolute inset-0 flex flex-col items-center justify-center"
    >
      {#if !isDragging}
        <IconUploadCloud size="lg" />
        <div class="text-center" id="upload-notice">
          Drag and Drop files or folders here <br />
          or <span class="underline">Click to browse</span>.
        </div>
      {:else}
        <IconDropFile size="lg" />
        <div class="text-center">Drop your files here</div>
      {/if}
      <div class="text-secondary pt-2 text-sm">
        Click <button
          on:click={() => {
            dispatch("showsupportedtypes", {
              message:
                "Currently we support the following MIME types for uploading:\n" +
                acceptedMimeTypes.join("\n")
            });
          }}
          class="hover:bg-hover-default pointer-events-auto underline">here</button
        > to see a list of supported filetypes.
      </div>
    </div>
  {/if}
  <input
    bind:this={dropzoneInput}
    type="file"
    multiple
    {name}
    accept={acceptedMimeTypes.join(",")}
    on:change={handleInputChange}
    on:focus={addFocusDecoration}
    on:blur={removeFocusDecoration}
    class="hidden h-0 w-0"
  />
</div>
