<script lang="ts">
  import { browser } from "$app/environment";
  import type { UploadedFile } from "@eneo/eneo-js";
  import { IconDocument } from "@eneo/icons/document";
  import { IconDownload } from "@eneo/icons/download";
  import CopyButton from "$lib/components/CopyButton.svelte";
  import { Markdown } from "$lib/components/markdown/index.js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";

  import type { Snippet } from "svelte";

  let {
    file,
    index = undefined,
    isTableView = false,
    children
  }: {
    file: UploadedFile;
    index?: number;
    isTableView?: boolean;
    children?: Snippet<[{ showFile: () => void }]>;
  } = $props();

  const eneo = getEneo();

  let loadedContent = $state<string | undefined>(undefined);
  let signedUrl = $state<string | undefined>(undefined);
  let loadingFile = $state(false);
  let loadError = $state(false);
  let isOpen = $state(false);

  // Text files include plain text, PDFs, DOCX, PPTX, etc. (all are returned as text from backend)
  const isTextFile = $derived(
    (file.mimetype?.includes("text") ||
      file.mimetype?.includes("pdf") ||
      file.mimetype?.includes("document") ||
      file.mimetype?.includes("presentation") ||
      file.mimetype?.includes("msword") ||
      file.mimetype?.includes("officedocument")) ??
      false
  );
  const isImageFile = $derived(file.mimetype?.includes("image") ?? false);
  const isAudioFile = $derived(file.mimetype?.includes("audio") ?? false);

  async function loadFile() {
    if (signedUrl) return true;

    loadingFile = true;
    loadError = false;

    try {
      const response = await eneo.files.generateSignedUrl({
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
      toast.error(m.error_loading_file());
    } finally {
      loadingFile = false;
    }

    return true;
  }

  async function downloadFile() {
    if (!browser) return;

    try {
      const response = await eneo.files.generateSignedUrl({
        fileId: file.id,
        expiresIn: 3600,
        contentDisposition: "attachment"
      });

      // Open in new tab for download
      window.open(response.url, "_blank");
    } catch (e) {
      console.error("Error generating download URL:", e);
      toast.error(m.error_downloading_file());
    }
  }

  const showFile = () => {
    isOpen = true;
    loadFile();
  };
</script>

<Dialog.Root bind:open={isOpen}>
  {#if children}
    {@render children({ showFile })}
  {:else}
    <Button
      variant="ghost"
      class={isTableView ? "-ml-1" : "bg-primary border-default max-w-[30ch] shadow-sm"}
      onclick={showFile}
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

      <span class="truncate">{file.name}</span>
    </Button>
  {/if}

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{file.name}</Dialog.Title>
      <Dialog.Description class="sr-only">
        {m.attachment_file_preview_for({ name: file.name })}
      </Dialog.Description>
    </Dialog.Header>

    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        <div class="p-4">
          {#if loadingFile}
            <pre>{m.loading()}</pre>
          {:else if loadError}
            <pre>{m.attachment_error_loading_content()}</pre>
          {:else if isTextFile && loadedContent}
            <Markdown source={loadedContent}></Markdown>
          {:else if isImageFile && signedUrl}
            <img src={signedUrl} alt={file.name} class="max-w-full rounded-lg" />
          {:else if isAudioFile && signedUrl}
            <audio controls class="w-full">
              <source src={signedUrl} type={file.mimetype} />
              {m.attachment_audio_not_supported()}
            </audio>
          {:else}
            <div class="text-center">
              <p class="mb-4">{m.preview_not_available()}</p>
              <Button variant="outline" onclick={downloadFile}>
                <IconDownload />
                {m.download_file()}
              </Button>
            </div>
          {/if}
        </div>
      </div>
    </div>

    <Dialog.Footer class={dialogLayout.footer}>
      <Button variant="ghost" onclick={downloadFile}>
        <IconDownload />
        {m.download_file()}
      </Button>

      {#if isTextFile && loadedContent}
        <CopyButton text={loadedContent} showLabel />
      {/if}

      <div class="flex-grow"></div>
      <Dialog.Close class={buttonVariants()}>{m.done()}</Dialog.Close>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
