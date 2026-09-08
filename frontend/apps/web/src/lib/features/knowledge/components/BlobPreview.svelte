<script lang="ts">
  import { browser } from "$app/environment";
  import type { InfoBlob } from "@eneo/eneo-js";
  import { IconCopy } from "@eneo/icons/copy";
  import { IconDocument } from "@eneo/icons/document";
  import { IconDownload } from "@eneo/icons/download";
  import { Button, Dialog, Markdown } from "@eneo/ui";
  import { getEneo } from "$lib/core/Eneo";
  import * as m from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  type BlobPreviewReference = {
    id: InfoBlob["id"];
    metadata: { title?: string | null };
    text?: InfoBlob["text"];
    original_available?: InfoBlob["original_available"];
  };

  export let blob: BlobPreviewReference;
  export let index: number | undefined = undefined;
  export let isTableView = false;

  const eneo = getEneo();

  // Use a separate state variable for the loaded text to avoid prop mutation
  let loadedBlobText: string | undefined = blob.text;
  let originalAvailable: boolean | undefined = blob.original_available;
  let loadingBlob = false;
  let loadError = false;
  let loadingOriginal = false;

  async function loadBlob() {
    if (!loadedBlobText || originalAvailable === undefined) {
      loadingBlob = true;
      loadError = false;
      try {
        const loadedBlob = await eneo.infoBlobs.get(blob);
        loadedBlobText = loadedBlob.text;
        if ("original_available" in loadedBlob) {
          originalAvailable = loadedBlob.original_available;
        }
      } catch (e) {
        loadError = true;
        console.error("Error retrieving blob content:", e);
        toast.error("Error retrieving reference, see console for details.");
      }
      loadingBlob = false;
    }
    return true;
  }

  let isOpen: Dialog.OpenState;

  async function downloadText() {
    await loadBlob();
    if (loadedBlobText && browser) {
      const file = new Blob([loadedBlobText], { type: "application/octet-stream;charset=utf-8" });
      const filename = blob.metadata.title
        ? `${blob.metadata.title}${blob.metadata.title.endsWith(".txt") ? "" : ".txt"}`
        : "Download.txt";
      if (window.showSaveFilePicker) {
        const handle = await window.showSaveFilePicker({ suggestedName: filename });
        const writable = await handle.createWritable();
        await writable.write(file);
        writable.close();
      } else {
        const a = document.createElement("a");
        a.download = filename;
        a.href = URL.createObjectURL(file);
        a.click();
        setTimeout(function () {
          URL.revokeObjectURL(a.href);
        }, 1500);
      }
    }
  }

  async function downloadOriginal() {
    if (!browser || loadingOriginal || !originalAvailable) return;

    loadingOriginal = true;
    try {
      const response = await eneo.infoBlobs.generateOriginalSignedUrl({
        infoBlobId: blob.id,
        contentDisposition: "attachment"
      });
      window.location.assign(response.url);
    } catch (e) {
      console.error("Error generating original download URL:", e);
      toast.error(m.error_downloading_original());
    } finally {
      loadingOriginal = false;
    }
  }

  let copyButtonText = m.copy_to_clipboard();
  async function copyText() {
    await loadBlob();
    if (loadedBlobText && browser) {
      navigator.clipboard.writeText(loadedBlobText);
      copyButtonText = m.copied_to_clipboard();
      setTimeout(() => {
        copyButtonText = m.copy_to_clipboard();
      }, 2000);
    }
  }

  const showBlob = () => {
    $isOpen = true;
    loadBlob();
  };
</script>

<Dialog.Root bind:isOpen>
  {#if $$slots.default}
    <slot {showBlob}></slot>
  {:else}
    <Button
      class={isTableView ? "-ml-1" : "bg-preview !border-default max-w-[30ch] border shadow-sm"}
      on:click={showBlob}
      padding="icon-leading"
    >
      {#if index}
        <span
          class="border-default bg-secondary min-h-7 min-w-7 rounded-md border border-b-2 text-center font-mono font-normal"
        >
          {index}
        </span>
      {:else}
        <IconDocument class="text-muted" />
      {/if}

      {blob.metadata.title}
    </Button>
  {/if}

  <Dialog.Content width="medium">
    <Dialog.Title>{blob.metadata.title}</Dialog.Title>
    <Dialog.Description hidden
      >{m.file_contents_of({ title: blob.metadata.title || "" })}</Dialog.Description
    >

    <Dialog.Section scrollable>
      <div class="p-4">
        {#if loadingBlob}
          <pre>{m.loading()}</pre>
        {:else if loadError}
          <pre>{m.attachment_error_loading_content()}</pre>
        {:else}
          <Markdown source={loadedBlobText ?? ""}></Markdown>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      {#if loadedBlobText}
        <Button variant="simple" on:click={downloadText} padding="icon-leading">
          <IconDownload />
          {m.download_extracted_text()}
        </Button>

        <Button variant="simple" padding="icon-leading" on:click={copyText}>
          <IconCopy />
          {copyButtonText}</Button
        >
        <div class="flex-grow"></div>
      {/if}
      {#if originalAvailable}
        <Button
          variant="simple"
          on:click={downloadOriginal}
          disabled={loadingOriginal}
          padding="icon-leading"
        >
          <IconDownload />
          {loadingOriginal ? m.downloading() : m.download_original()}
        </Button>
      {/if}
      <Button variant="primary" is={close}>{m.done()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
