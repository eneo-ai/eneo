<script lang="ts">
  import { browser } from "$app/environment";
  import type { InfoBlob } from "@intric/intric-js";
  import { IconDocument } from "@intric/icons/document";
  import { Button, Dialog, Markdown } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  export let blob: InfoBlob;
  export let index: number | undefined = undefined;
  export let isTableView = false;

  const intric = getIntric();

  let loadingBlob = false;
  async function loadBlob() {
    if (!blob.text) {
      loadingBlob = true;
      try {
        blob = await intric.infoBlobs.get(blob);
      } catch (e) {
        alert(m.error_retrieving_reference_see_console());
        console.error(e);
      }
      loadingBlob = false;
    }
    return true;
  }

  let isOpen: Dialog.OpenState;

  async function downloadText() {
    await loadBlob();
    if (blob.text && browser) {
      const file = new Blob([blob.text], { type: "application/octet-stream;charset=utf-8" });
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

  let copyButtonText = m.copy_to_clipboard();
  function copyText() {
    if (blob.text && browser) {
      navigator.clipboard.writeText(blob.text);
      copyButtonText = m.copied();
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
    <Dialog.Description hidden>{m.file_contents_of({ title: blob.metadata.title })}</Dialog.Description>

    <Dialog.Section scrollable>
      <div class="p-4">
        {#if loadingBlob}
          <pre>{m.loading()}</pre>
        {:else}
          <Markdown source={blob.text ?? ""}></Markdown>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      {#if blob.text}
        <Button variant="simple" on:click={downloadText} padding="icon-leading">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="1.5"
            stroke="currentColor"
            class="h-6 w-6"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
            />
          </svg>
          {m.download_extracted_text()}
        </Button>

        <Button variant="simple" padding="icon-leading" on:click={copyText}>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="1.5"
            stroke="currentColor"
            class="h-6 w-6"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75"
            />
          </svg>
          {copyButtonText}</Button
        >
        <div class="flex-grow"></div>
      {/if}
      <Button variant="primary" is={close}>{m.done()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
