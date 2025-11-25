<script lang="ts">
  import { browser } from "$app/environment";
  import type { UploadedFile } from "@intric/intric-js";
  import { IconDocument } from "@intric/icons/document";
  import { Button, Dialog, Markdown } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";

  import type { Snippet } from "svelte";

  export let file: UploadedFile;
  export let index: number | undefined = undefined;
  export let isTableView = false;
  export let isOpen: Dialog.OpenState | undefined = undefined;
  export let children: Snippet<[{ showFile: () => void }]> | undefined = undefined;

  const intric = getIntric();

  let loadedContent: string | undefined = undefined;
  let signedUrl: string | undefined = undefined;
  let loadingFile = false;
  let loadError = false;

  // Text files include plain text, PDFs, DOCX, PPTX, etc. (all are returned as text from backend)
  const isTextFile =
    (file.mimetype?.includes("text") ||
    file.mimetype?.includes("pdf") ||
    file.mimetype?.includes("document") ||
    file.mimetype?.includes("presentation") ||
    file.mimetype?.includes("msword") ||
    file.mimetype?.includes("officedocument")) ?? false;
  const isImageFile = file.mimetype?.includes("image") ?? false;
  const isAudioFile = file.mimetype?.includes("audio") ?? false;

  async function loadFile() {
    if (signedUrl) return true;

    loadingFile = true;
    loadError = false;

    try {
      const response = await intric.files.generateSignedUrl({
        fileId: file.id,
        expiresIn: 3600,
        contentDisposition: "inline"
      });
      signedUrl = response.url;

      // If text file, fetch content for preview
      if (isTextFile) {
        const contentResponse = await fetch(signedUrl);
        if (contentResponse.ok) {
          loadedContent = await contentResponse.text();
        } else {
          throw new Error("Failed to load file content");
        }
      }
    } catch (e) {
      loadError = true;
      console.error("Error loading file:", e);
      alert("Error loading file, see console for details.");
    } finally {
      loadingFile = false;
    }

    return true;
  }

  async function downloadFile() {
    if (!browser) return;

    try {
      const response = await intric.files.generateSignedUrl({
        fileId: file.id,
        expiresIn: 3600,
        contentDisposition: "attachment"
      });

      // Open in new tab for download
      window.open(response.url, "_blank");
    } catch (e) {
      console.error("Error generating download URL:", e);
      alert("Error downloading file, see console for details.");
    }
  }

  let copyButtonText = "Copy to clipboard";
  async function copyText() {
    await loadFile();
    if (loadedContent && browser) {
      navigator.clipboard.writeText(loadedContent);
      copyButtonText = "Copied!";
      setTimeout(() => {
        copyButtonText = "Copy to clipboard";
      }, 2000);
    }
  }

  const showFile = () => {
    if (isOpen) {
      $isOpen = true;
      loadFile();
    }
  };
</script>

<Dialog.Root bind:isOpen>
  {#if children}
    {@render children({ showFile })}
  {:else}
    <Button
      class={isTableView ? "-ml-1" : "bg-preview !border-default max-w-[30ch] border shadow-sm"}
      on:click={showFile}
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

      {file.name}
    </Button>
  {/if}

  <Dialog.Content width="medium">
    <Dialog.Title>{file.name}</Dialog.Title>
    <Dialog.Description hidden>File preview for {file.name}</Dialog.Description>

    <Dialog.Section scrollable>
      <div class="p-4">
        {#if loadingFile}
          <pre>Loading...</pre>
        {:else if loadError}
          <pre>Error loading content. Please try again.</pre>
        {:else if isTextFile && loadedContent}
          <Markdown source={loadedContent}></Markdown>
        {:else if isImageFile && signedUrl}
          <img src={signedUrl} alt={file.name} class="max-w-full rounded-lg" />
        {:else if isAudioFile && signedUrl}
          <!-- svelte-ignore a11y-media-has-caption -->
          <audio controls class="w-full">
            <source src={signedUrl} type={file.mimetype} />
            Your browser does not support the audio element.
          </audio>
        {:else}
          <div class="text-center">
            <p class="mb-4">Preview not available for this file type</p>
            <Button on:click={downloadFile} variant="outlined">
              Download file
            </Button>
          </div>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button variant="simple" on:click={downloadFile} padding="icon-leading">
        Download file
      </Button>

      {#if isTextFile && loadedContent}
        <Button variant="simple" padding="icon-leading" on:click={copyText}>
          {copyButtonText}
        </Button>
      {/if}

      <div class="flex-grow"></div>
      <Button variant="primary" is={close}>Done</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
