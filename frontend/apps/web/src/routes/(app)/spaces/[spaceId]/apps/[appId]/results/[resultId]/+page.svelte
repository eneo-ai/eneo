<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { IconDownload } from "@eneo/icons/download";
  import { Markdown } from "$lib/components/markdown/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import dayjs from "dayjs";
  import utc from "dayjs/plugin/utc";
  import AppResultStatus from "$lib/features/apps/components/AppResultStatus.svelte";
  import AppResultToolbar from "$lib/features/apps/components/AppResultToolbar.svelte";
  import { createAppRunResult } from "$lib/features/apps/createAppRunResult.svelte";
  import Tabbar from "$lib/components/layout/Page/Tabbar.svelte";
  import TabTrigger from "$lib/components/layout/Page/TabTrigger.svelte";
  import Tab from "$lib/components/layout/Page/Tab.svelte";
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte.js";
  import { getEneo } from "$lib/core/Eneo.js";
  import { browser } from "$app/environment";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  dayjs.extend(utc);

  const { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const eneo = getEneo();
  const attachmentUrlService = getAttachmentUrlService();

  const run = createAppRunResult(() => data);

  let printElement = $state<HTMLDivElement>();
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {data.app
      .name}</title
  >
</svelte:head>

{#snippet formattedResult()}
  {#if run.result.output}
    <AppResultToolbar
      type="output"
      text={run.result.output}
      fileName={run.textFileName}
      {printElement}
      floating
      class="hidden-in-print absolute -right-[5.5rem] z-10"
    />
    <Markdown source={run.result.output}></Markdown>
  {:else}
    <div class="flex items-center justify-center gap-2">
      <span class="text-secondary">{m.no_output_generated()}</span>
    </div>
  {/if}
{/snippet}

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: m.back(),
        href: `/spaces/${$currentSpace.routeId}/apps/${data.app.id}`
      }}
      title={run.title}
    ></Page.Title>

    <Page.Flex>
      <Button
        variant="ghost"
        href={localizeHref(`/spaces/${$currentSpace.routeId}/apps/${data.app.id}/edit`)}
        >{m.edit()}</Button
      >
      <Button href={localizeHref(`/spaces/${$currentSpace.routeId}/apps/${data.app.id}`)}
        >{m.new_run()}</Button
      >
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <div class="flex items-start justify-center gap-16 p-8">
      <div
        class=" prose border-default bg-primary relative min-h-72 w-full max-w-[90ch] rounded-sm border px-16 py-8 text-lg shadow-lg"
      >
        <div class="printable-document relative flex flex-col py-4" bind:this={printElement}>
          {#if run.isComplete}
            {#if run.transcribedFiles.length > 0}
              <div class="hidden-in-print -mt-2 h-20">
                <Tabbar>
                  <TabTrigger tab="results">{m.results()}</TabTrigger>
                  <TabTrigger tab="transcription">{m.transcription()}</TabTrigger>
                </Tabbar>
              </div>
              <Tab id="results">
                {@render formattedResult()}
              </Tab>
              <Tab id="transcription">
                <div class="flex flex-col gap-8">
                  {#each run.transcribedFiles as file (file.id)}
                    {@const url = attachmentUrlService.getUrl(file)}
                    <AppResultToolbar
                      type="transcription"
                      text={file.transcription}
                      fileName={run.textFileName}
                      {printElement}
                      floating
                      class="hidden-in-print absolute -right-[5.5rem] z-10"
                    />

                    <div class="border-stronger bg-secondary rounded-xl border print:border-none">
                      {#if url}
                        <div
                          class="hidden-in-print border-stronger bg-primary -m-[1px] rounded-xl border p-2 shadow"
                        >
                          <div class="flex items-center justify-between gap-4 px-1 pb-2">
                            <div class="flex gap-2">
                              <UploadedFileIcon {file}></UploadedFileIcon>
                              {file.name}
                            </div>
                            <Button variant="ghost" href={url}>
                              <IconDownload></IconDownload>
                              {m.download()}</Button
                            >
                          </div>
                          <audio
                            controls
                            src={url}
                            class="border-stronger h-8 w-full rounded-full border shadow-sm"
                          ></audio>
                        </div>
                      {/if}
                      <div class="p-4">
                        <Markdown source={file.transcription}></Markdown>
                      </div>
                    </div>
                  {/each}
                </div>
              </Tab>
            {:else if run.result.output}
              {@render formattedResult()}
              <!-- Need to check for browser as we make a fetch request in the await -->
            {:else if browser && run.result.status === "failed" && run.result.input.files.length > 0}
              <div class="flex flex-grow flex-col items-center justify-center gap-2">
                <span class="py-2">
                  {m.app_run_failed_files_list()}
                </span>

                {#each run.result.input.files as file (file.id)}
                  {#await eneo.files.generateSignedUrl( { fileId: file.id, contentDisposition: "attachment" } ) then { url }}
                    <Button variant="ghost" href={url} class="no-underline"
                      ><IconDownload></IconDownload>{m.download()} "{file.name}"</Button
                    >
                  {/await}
                {/each}
              </div>
            {:else}
              <div class="flex flex-grow flex-col items-center justify-center gap-2">
                <span class="py-2">{m.no_outputs_generated()}</span>
              </div>
            {/if}
          {:else}
            <div class="flex h-[50vh] flex-col items-center justify-center gap-4">
              <div class="audio-wave">
                <div class="wave-bar" style="animation-delay: 0s"></div>
                <div class="wave-bar" style="animation-delay: 0.1s"></div>
                <div class="wave-bar" style="animation-delay: 0.2s"></div>
                <div class="wave-bar" style="animation-delay: 0.3s"></div>
                <div class="wave-bar" style="animation-delay: 0.4s"></div>
              </div>
              <span class="text-secondary">{m.result_being_generated()}</span>
            </div>
          {/if}
        </div>
      </div>
      <div class="sticky top-8 flex min-w-[26ch] flex-col gap-4">
        <div class="flex flex-col gap-3 pt-2">
          <div class="border-dimmer flex items-center justify-between border-b">
            <span>{m.started()}</span><span class="font-mono text-sm"
              >{dayjs(run.result.created_at).format("YYYY-MM-DD HH:mm")}</span
            >
          </div>
          {#if run.isComplete}
            <div class="border-dimmer flex items-center justify-between border-b">
              <span>{m.finished()}</span><span class="font-mono text-sm"
                >{dayjs(run.result.finished_at).format("YYYY-MM-DD HH:mm")}</span
              >
            </div>
          {/if}
          <AppResultStatus run={run.result} variant="full"></AppResultStatus>

          {#each run.result.input.files as file (file.id)}
            <div
              class="border-default bg-primary flex items-center gap-2 rounded-lg border px-4 py-3 shadow"
            >
              <UploadedFileIcon class="min-w-6" {file} />
              <span
                class="line-clamp-1 overflow-hidden break-words overflow-ellipsis hover:line-clamp-5"
              >
                {file.name}
              </span>
            </div>
          {/each}
        </div>
      </div>
    </div>
  </Page.Main>
</Page.Root>

<style lang="postcss">
  @reference "@eneo/ui/styles";

  /* Audio wave loading animation */
  .audio-wave {
    @apply flex h-8 items-center gap-1;
  }

  .wave-bar {
    @apply w-1 rounded-full bg-blue-500;
    animation: wave 1s ease-in-out infinite;
  }

  @keyframes wave {
    0%,
    100% {
      height: 8px;
    }
    50% {
      height: 24px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .wave-bar {
      animation: none;
      height: 16px;
    }
  }
</style>
