<script lang="ts">
  import { IconCopy } from "@intric/icons/copy";
  import { IconDownload } from "@intric/icons/download";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconPrint } from "@intric/icons/print";
  import { Button, Markdown, Tooltip } from "@intric/ui";
  import dayjs from "dayjs";
  import utc from "dayjs/plugin/utc";
  import { getResultTitle } from "$lib/features/apps/getResultTitle.js";
  import AppResultStatus from "$lib/features/apps/components/AppResultStatus.svelte";
  import { onMount } from "svelte";
  import { getIntricSocket } from "$lib/core/IntricSocket.js";
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import type { UploadedFile } from "@intric/intric-js";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte.js";
  import { getIntric } from "$lib/core/Intric.js";
  import { browser } from "$app/environment";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { fade, fly } from "svelte/transition";
  import { quadInOut } from "svelte/easing";

  dayjs.extend(utc);

  const { data } = $props();

  const { subscribe } = getIntricSocket();
  const intric = getIntric();

  const attachmentUrlService = getAttachmentUrlService();

  let result = $state(data.result);
  const resultTitle = $derived(getResultTitle(result));

  async function downloadAsText(text?: string | null) {
    if (!text) {
      alert(m.not_output_to_save());
      return;
    }
    const file = new Blob([text], { type: "application/octet-stream;charset=utf-8" });
    const suggestedName =
      data.app.name + dayjs(result.created_at).format(" YYYY-MM-DD HH:mm") + ".txt";
    if (window.showSaveFilePicker) {
      const handle = await window.showSaveFilePicker({ suggestedName });
      const writable = await handle.createWritable();
      await writable.write(file);
      writable.close();
    } else {
      const a = document.createElement("a");
      a.download = suggestedName;
      a.href = URL.createObjectURL(file);
      a.click();
      setTimeout(function () {
        URL.revokeObjectURL(a.href);
      }, 1500);
    }
  }

  let printElement = $state<HTMLDivElement>();
  function print() {
    if (!printElement) return;
    const printNode = printElement.cloneNode(true);
    document.body.appendChild(printNode);
    document.body.classList.add("print-mode");
    window.print();
    document.body.classList.remove("print-mode");
    document.body.removeChild(printNode);
  }

  function copyText(text?: string | null) {
    if (text) {
      navigator.clipboard.writeText(text);
    } else {
      alert(m.no_copyable_output());
    }
  }

  const isRunComplete = $derived(!(result.status === "in progress" || result.status === "queued"));

  function isTranscribedFile(file: UploadedFile): file is UploadedFile & { transcription: string } {
    return file.transcription !== null && file.transcription !== undefined;
  }

  let transcribedFiles = $derived.by(() => {
    if (!result.output) return [];
    return result.input.files.filter((file) => isTranscribedFile(file));
  });

  let activeTab: "results" | "transcription" = $state("results");

  onMount(() => {
    if (isRunComplete) return;

    const unsubscriber = subscribe("app_run_updates", async (update) => {
      if (update.id === data.result.id) {
        result = await intric.apps.runs.get(result);
      }
    });

    if (result.status === "queued") {
      intric.apps.runs.get(result).then((updatedResult) => {
        result = updatedResult;
      });
    }

    return unsubscriber;
  });
</script>

<svelte:head>
  <title>Eneo.ai – Dashboard – {data.app.name}</title>
</svelte:head>

{#snippet downloadButtons(type: "output" | "transcription", text?: string)}
  <div class="flex gap-1 pb-2">
    <Tooltip text={m.print_save_type_pdf({ type })} placement="bottom">
      <Button on:click={print} padding="icon" variant="outlined">
        <IconPrint size="md" />
      </Button>
    </Tooltip>

    <Tooltip text={m.download_type_raw_text({ type })} placement="bottom">
      <Button on:click={() => downloadAsText(text)} padding="icon" variant="outlined">
        <IconDownload />
      </Button>
    </Tooltip>

    <Tooltip text={m.copy_type({ type })} placement="bottom">
      <Button on:click={() => copyText(text)} padding="icon" variant="outlined">
        <IconCopy />
      </Button>
    </Tooltip>
  </div>
{/snippet}

<div class="outer bg-primary flex w-full flex-col">
  <div
    class="bg-primary sticky top-0 z-10 flex items-center justify-between px-3.5 py-3 backdrop-blur-md"
    in:fade={{ duration: 50 }}
  >
    <a
      href={localizeHref(`/dashboard/app/${data.app.id}`)}
      class="flex max-w-[calc(100%_-_7rem)] flex-grow items-center rounded-lg"
    >
      <span
        class="border-default hover:bg-hover-dimmer flex h-8 w-8 items-center justify-center rounded-lg border"
        >←</span
      >
      <h1
        in:fly|global={{
          x: -5,
          duration: 300,
          easing: quadInOut,
          opacity: 0.3
        }}
        class="truncate px-3 py-1 text-xl font-extrabold"
      >
        {resultTitle}
      </h1>
    </a>
    <Button variant="primary" href={localizeHref(`/dashboard/app/${data.app.id}`)} class="!rounded-lg !px-5 !py-1">
      {m.new_run()}
    </Button>
  </div>

  <div class="border-default flex flex-wrap items-center gap-4 border-b px-4 py-2">
    <AppResultStatus run={result} variant="full" />
    <span class="text-secondary text-sm">
      {dayjs(result.created_at).format("YYYY-MM-DD HH:mm")}
    </span>
  </div>

  {#if transcribedFiles.length > 0}
    <div class="border-default flex border-b px-3.5">
      <button
        class="border-b-2 px-4 py-2 text-sm font-medium transition-colors"
        class:border-[var(--color-ui-blue-600)]={activeTab === "results"}
        class:text-primary={activeTab === "results"}
        class:border-transparent={activeTab !== "results"}
        class:text-secondary={activeTab !== "results"}
        onclick={() => (activeTab = "results")}
      >
        {m.results()}
      </button>
      <button
        class="border-b-2 px-4 py-2 text-sm font-medium transition-colors"
        class:border-[var(--color-ui-blue-600)]={activeTab === "transcription"}
        class:text-primary={activeTab === "transcription"}
        class:border-transparent={activeTab !== "transcription"}
        class:text-secondary={activeTab !== "transcription"}
        onclick={() => (activeTab = "transcription")}
      >
        {m.transcription()}
      </button>
    </div>
  {/if}

  <div class="flex-grow overflow-y-auto p-4">
    {#if isRunComplete}
      {#if transcribedFiles.length > 0 && activeTab === "transcription"}
        <div class="flex flex-col gap-4">
          {#each transcribedFiles as file (file.id)}
            {@const url = attachmentUrlService.getUrl(file)}
            {@render downloadButtons("transcription", file.transcription)}

            <div class="border-stronger bg-secondary rounded-xl border">
              {#if url}
                <div class="border-stronger bg-primary rounded-t-xl border-b p-2">
                  <div class="flex items-center justify-between gap-4 px-1 pb-2">
                    <div class="flex gap-2">
                      <UploadedFileIcon {file} />
                      <span class="truncate">{file.name}</span>
                    </div>
                    <Button href={url} padding="icon">
                      <IconDownload />
                    </Button>
                  </div>
                  <audio
                    controls
                    src={url}
                    class="border-stronger h-8 w-full rounded-full border shadow-sm"
                  ></audio>
                </div>
              {/if}
              <div class="prose p-4">
                <Markdown source={file.transcription} />
              </div>
            </div>
          {/each}
        </div>
      {:else if result.output}
        {@render downloadButtons("output", result.output)}
        <div
          class="prose border-default bg-primary rounded-lg border p-4 shadow"
          bind:this={printElement}
        >
          <Markdown source={result.output} />
        </div>
      {:else if browser && result.status === "failed" && result.input.files.length > 0}
        <div class="flex flex-col items-center justify-center gap-4 py-8">
          <span class="text-secondary">{m.app_run_failed_files_list()}</span>
          {#each result.input.files as file (file.id)}
            {#await intric.files.url({ id: file.id, download: true }) then fileUrl}
              <Button href={fileUrl} variant="outlined">
                <IconDownload />
                {m.download()} "{file.name}"
              </Button>
            {/await}
          {/each}
        </div>
      {:else}
        <div class="flex flex-col items-center justify-center py-8">
          <span class="text-secondary">{m.no_outputs_generated()}</span>
        </div>
      {/if}
    {:else}
      <div class="flex h-[50vh] flex-col items-center justify-center gap-2">
        <IconLoadingSpinner class="animate-spin" />
        <span class="text-secondary">{m.result_being_generated()}</span>
      </div>
    {/if}

    {#if result.input.files.length > 0}
      <div class="mt-4 flex flex-col gap-2">
        <span class="text-secondary text-sm font-medium">{m.input_files()}</span>
        {#each result.input.files as file (file.id)}
          <div class="border-default bg-primary flex items-center gap-2 rounded-lg border px-4 py-3">
            <UploadedFileIcon class="min-w-6" {file} />
            <span class="truncate">{file.name}</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>

<style>
  @media (display-mode: standalone) {
    .outer {
      background-color: var(--background-primary);
      overflow-y: auto;
      margin: 0 0.5rem;
      border-radius: 1rem;
      box-shadow: 0 4px 10px 0px rgba(0, 0, 0, 0.1);
      max-height: 100%;
    }
  }

  @container (min-width: 1000px) {
    .outer {
      margin: 1.5rem;
      border-radius: 1rem;
      box-shadow: 0 4px 10px 0px rgba(0, 0, 0, 0.1);
      max-width: 1400px;
      overflow: hidden;
    }
  }
</style>
