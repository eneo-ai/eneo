<script lang="ts">
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { IconDownload } from "@eneo/icons/download";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { Markdown } from "$lib/components/markdown/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import AppResultStatus from "$lib/features/apps/components/AppResultStatus.svelte";
  import AppResultToolbar from "$lib/features/apps/components/AppResultToolbar.svelte";
  import { createAppRunResult } from "$lib/features/apps/createAppRunResult.svelte";
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte.js";
  import { getEneo } from "$lib/core/Eneo.js";
  import { browser } from "$app/environment";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { fade, fly } from "svelte/transition";
  import { quadInOut } from "svelte/easing";

  const { data } = $props();

  const eneo = getEneo();
  const attachmentUrlService = getAttachmentUrlService();

  const run = createAppRunResult(() => data);

  let printElement = $state<HTMLDivElement>();
  let activeTab: "results" | "transcription" = $state("results");
</script>

<svelte:head>
  <title>Eneo.ai – {m.dashboard()} – {data.app.name}</title>
</svelte:head>

<div class="outer bg-primary flex w-full flex-col">
  <div
    class="bg-primary sticky top-0 z-10 flex items-center justify-between px-3.5 py-3 backdrop-blur-md"
    in:fade={{ duration: 50 }}
  >
    <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing with dynamic app ID -->
    <a
      href={localizeHref(`/dashboard/app/${data.app.id}`)}
      class="flex max-w-[calc(100%_-_7rem)] flex-grow items-center rounded-lg"
    >
      <!-- eslint-enable svelte/no-navigation-without-resolve -->
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
        {run.title}
      </h1>
    </a>
    <Button href={localizeHref(`/dashboard/app/${data.app.id}`)} class="px-5">
      {m.new_run()}
    </Button>
  </div>

  <div class="border-default flex flex-wrap items-center gap-4 border-b px-4 py-2">
    <AppResultStatus run={run.result} variant="full" />
    <span class="text-secondary text-sm">
      {formatDateTime(run.result.created_at)}
    </span>
  </div>

  {#if run.transcribedFiles.length > 0}
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
    {#if run.isComplete}
      {#if run.transcribedFiles.length > 0 && activeTab === "transcription"}
        <div class="flex flex-col gap-4">
          {#each run.transcribedFiles as file (file.id)}
            {@const url = attachmentUrlService.getUrl(file)}
            <AppResultToolbar
              type="transcription"
              text={file.transcription}
              fileName={run.textFileName}
              {printElement}
              class="pb-2"
            />

            <div class="border-stronger bg-secondary rounded-xl border">
              {#if url}
                <div class="border-stronger bg-primary rounded-t-xl border-b p-2">
                  <div class="flex items-center justify-between gap-4 px-1 pb-2">
                    <div class="flex gap-2">
                      <UploadedFileIcon {file} />
                      <span class="truncate">{file.name}</span>
                    </div>
                    <Button
                      href={url}
                      variant="ghost"
                      size="icon"
                      aria-label={`${m.download()} ${file.name}`}
                    >
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
      {:else if run.result.output}
        <AppResultToolbar
          type="output"
          text={run.result.output}
          fileName={run.textFileName}
          {printElement}
          class="pb-2"
        />
        <div
          class="printable-document prose border-default bg-primary rounded-lg border p-4 shadow"
          bind:this={printElement}
        >
          <Markdown source={run.result.output} />
        </div>
      {:else if browser && run.result.status === "failed" && run.result.input.files.length > 0}
        <div class="flex flex-col items-center justify-center gap-4 py-8">
          <span class="text-secondary">{m.app_run_failed_files_list()}</span>
          {#each run.result.input.files as file (file.id)}
            {#await eneo.files.generateSignedUrl( { fileId: file.id, expiresIn: 3600, contentDisposition: "attachment" } ) then signedFile}
              <Button href={signedFile.url} variant="outline">
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

    {#if run.result.input.files.length > 0}
      <div class="mt-4 flex flex-col gap-2">
        <span class="text-secondary text-sm font-medium">{m.input_files()}</span>
        {#each run.result.input.files as file (file.id)}
          <div
            class="border-default bg-primary flex items-center gap-2 rounded-lg border px-4 py-3"
          >
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
