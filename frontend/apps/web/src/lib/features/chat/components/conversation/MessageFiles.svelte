<!--
  The files a message was sent with. Images keep their thumbnails. Up to
  three documents are shown as chips; more are one bundle that opens the
  panel's full list of uploads at this message's own group, so a long upload
  list never stretches the chat. A message still waiting for its uploads shows their progress here.
-->
<script lang="ts">
  import { getMessageContext } from "../../MessageContext.svelte";
  import { uploadGroupKey } from "../../conversationUploads";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import AsyncImage from "$lib/components/AsyncImage.svelte";
  import { m } from "$lib/paraglide/messages";
  import { fileExtension } from "$lib/core/formatting/fileExtension";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { getFilePreview } from "$lib/features/file-preview/FilePreview.svelte";
  import ArrowUpRight from "@lucide/svelte/icons/arrow-up-right";
  import Check from "@lucide/svelte/icons/check";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import ChevronUp from "@lucide/svelte/icons/chevron-up";
  import Files from "@lucide/svelte/icons/files";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import type { PendingUpload } from "../../ChatService.svelte";

  const attachmentUrlService = getAttachmentUrlService();
  const preview = getFilePreview();
  const { current } = getMessageContext();

  // From this many documents the message shows one bundle instead of chips.
  const BUNDLE_FROM = 4;

  // A message sent before its attachments finished uploading mirrors their
  // progress here until the request is issued; then `files` takes over.
  const pendingUploads = $derived(
    (current() as { pending_uploads?: PendingUpload[] }).pending_uploads ?? []
  );
  const pendingDone = $derived(
    pendingUploads.filter((upload) => upload.status === "completed").length
  );
  const pendingPercent = $derived(
    pendingUploads.length === 0
      ? 0
      : Math.round(
          pendingUploads.reduce(
            (sum, upload) => sum + (upload.status === "completed" ? 100 : upload.progress),
            0
          ) / pendingUploads.length
        )
  );

  const allFiles = $derived.by(() =>
    current().files.map((file) => {
      const isImage = file.mimetype.includes("image");
      return {
        id: file.id,
        name: file.name,
        type: isImage ? ("image" as const) : ("generic" as const),
        url: isImage ? (attachmentUrlService.getUrl(file) ?? null) : null,
        extension: fileExtension(file.name),
        mimetype: file.mimetype,
        // The uploaded file's size; `size` counts the extracted text of a document.
        size: file.original_size ?? file.size,
        // A file with a renderer opens in the conversation's preview panel.
        previewable: preview?.canPreview(file) ?? false,
        source: file
      };
    })
  );

  const images = $derived(allFiles.filter((f) => f.type === "image"));
  const documents = $derived(allFiles.filter((f) => f.type === "generic"));
  const bundled = $derived(documents.length >= BUNDLE_FROM);

  // The bundle is the opener of the panel's overview while that is on show.
  let bundle = $state<HTMLButtonElement | null>(null);
  const bundleShown = $derived(preview?.isOverviewOpener(bundle) ?? false);
  // Without a panel (a read-only transcript) the bundle unfolds in place.
  let expanded = $state(false);

  // The first names, how many of each type, and the total size on one line.
  const summaryOf = (files: Array<{ name: string; extension: string; size: number }>) => {
    const names =
      files
        .slice(0, 3)
        .map((file) => file.name)
        .join(", ") + (files.length > 3 ? "…" : "");
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- a tally, never rendered
    const counts = new Map<string, number>();
    for (const file of files) {
      const type = file.extension || m.unknown();
      counts.set(type, (counts.get(type) ?? 0) + 1);
    }
    const types = [...counts]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([type, count]) => `${type} ${count}`);
    const bytes = files.reduce((sum, file) => sum + file.size, 0);
    return [names, ...types, bytes > 0 ? formatBytes(bytes) : ""].filter(Boolean).join(" · ");
  };
  const summary = $derived(summaryOf(documents));

  function toggleBundle(event: MouseEvent & { currentTarget: HTMLButtonElement }) {
    if (!preview) {
      expanded = !expanded;
    } else if (bundleShown) {
      preview.closeOverview();
    } else {
      preview.showOverview("uploads", event.currentTarget, uploadGroupKey(current()));
    }
  }

  const chipClass =
    "flex h-8 max-w-full min-w-0 items-center gap-1.5 rounded-lg border px-1.5 shadow-sm";
  const bundleClass =
    "bg-primary flex h-12 w-full max-w-[42rem] items-center gap-3 rounded-lg border px-3 text-left shadow-sm transition-colors";
</script>

{#snippet chip(file: (typeof documents)[number])}
  {@const Icon = pickFileIcon(file.mimetype)}
  <span
    class="bg-accent-dimmer text-accent-stronger flex size-5 flex-shrink-0 items-center justify-center rounded"
  >
    <Icon class="size-3" aria-hidden="true" />
  </span>
  <span class="text-default min-w-0 truncate text-xs">{file.name}</span>
  <span class="text-tertiary flex-shrink-0 text-[11px] tabular-nums">
    {file.extension}{file.size > 0 ? ` · ${formatBytes(file.size)}` : ""}
  </span>
{/snippet}

{#snippet chips(files: typeof documents)}
  <div class="flex max-w-[42rem] flex-wrap justify-end gap-1.5">
    {#each files as file (file.id)}
      {#if file.previewable}
        {@const previewing = preview?.isOpen(file) ?? false}
        <button
          type="button"
          aria-label={m.file_preview_open({ name: file.name })}
          aria-expanded={previewing}
          onclick={(event) => preview?.toggle(file.source, event.currentTarget)}
          class="{chipClass} bg-primary hover:bg-secondary focus-visible:ring-accent-default transition-colors focus-visible:ring-2 focus-visible:outline-none {previewing
            ? 'border-accent-default'
            : 'border-default hover:border-stronger'}"
          title={file.name}
        >
          {@render chip(file)}
        </button>
      {:else}
        <div class="{chipClass} border-default bg-primary" title={file.name}>
          {@render chip(file)}
        </div>
      {/if}
    {/each}
  </div>
{/snippet}

{#if pendingUploads.length > 0}
  <div class="flex w-full flex-col items-end gap-2">
    {#if pendingUploads.length >= BUNDLE_FROM}
      <div class="{bundleClass} border-default" role="status">
        <span
          class="bg-accent-dimmer text-accent-stronger flex size-8 flex-shrink-0 items-center justify-center rounded-md"
        >
          <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
        </span>
        <span class="flex min-w-0 flex-1 flex-col gap-1 leading-tight">
          <span class="text-default truncate text-sm font-medium">
            {m.attachments_bundle_title({ count: pendingUploads.length })}
          </span>
          <span class="text-tertiary flex items-center gap-2 text-[11px] tabular-nums">
            <span
              class="bg-secondary h-1 w-24 flex-shrink-0 overflow-hidden rounded-full"
              role="progressbar"
              aria-valuenow={pendingPercent}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <span
                class="bg-accent-default block h-full transition-[width]"
                style="width: {pendingPercent}%"
              ></span>
            </span>
            {m.attachments_pending_progress({ done: pendingDone, total: pendingUploads.length })}
          </span>
        </span>
      </div>
    {:else}
      <div class="flex max-w-[42rem] flex-wrap justify-end gap-1.5" role="list">
        {#each pendingUploads as upload (upload.id)}
          {@const Icon = pickFileIcon(upload.mimetype)}
          {@const uploading = upload.status !== "completed"}
          <div
            role="listitem"
            class="{chipClass} border-default bg-primary relative overflow-hidden"
            title={upload.name}
          >
            <span
              class="bg-accent-dimmer text-accent-stronger flex size-5 flex-shrink-0 items-center justify-center rounded"
            >
              {#if uploading}
                <LoaderCircle class="size-3 animate-spin" aria-hidden="true" />
              {:else}
                <Icon class="size-3" aria-hidden="true" />
              {/if}
            </span>
            <span class="text-default min-w-0 truncate text-xs">{upload.name}</span>
            <span class="text-tertiary flex-shrink-0 text-[11px] tabular-nums">
              {#if uploading}
                {upload.progress} %
              {:else}
                {fileExtension(upload.name)}{upload.size > 0
                  ? ` · ${formatBytes(upload.size)}`
                  : ""}
              {/if}
            </span>
            {#if uploading}
              <span
                class="bg-accent-default absolute inset-x-0 bottom-0 h-0.5 transition-[width]"
                style="width: {upload.progress}%"
              ></span>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </div>
{:else if allFiles.length > 0}
  <div class="flex w-full flex-col items-end gap-2">
    {#if images.length > 0}
      <div class="flex flex-wrap justify-end gap-2">
        {#each images as image (image.id)}
          <div class="ml-12 overflow-clip rounded-lg border shadow-md">
            <AsyncImage url={image.url} fixedAspectRatio={false}></AsyncImage>
          </div>
        {/each}
      </div>
    {/if}

    {#if bundled}
      <button
        type="button"
        bind:this={bundle}
        aria-expanded={preview ? bundleShown : expanded}
        aria-label={m.attachments_bundle_open_label({ count: documents.length })}
        onclick={toggleBundle}
        class="{bundleClass} hover:bg-secondary focus-visible:ring-accent-default focus-visible:ring-2 focus-visible:outline-none {bundleShown
          ? 'border-accent-default'
          : 'border-default hover:border-stronger'}"
      >
        <span
          class="bg-accent-dimmer text-accent-stronger flex size-8 flex-shrink-0 items-center justify-center rounded-md"
        >
          <Files class="size-4" aria-hidden="true" />
        </span>
        <span class="flex min-w-0 flex-1 flex-col leading-tight">
          <span class="text-default truncate text-sm font-medium">
            {m.attachments_bundle_title({ count: documents.length })}
          </span>
          <span class="text-tertiary truncate text-[11px] tabular-nums">{summary}</span>
        </span>
        <span class="text-tertiary flex flex-shrink-0 items-center gap-1 text-xs">
          {#if !preview}
            {expanded ? m.attachments_show_less() : m.attachments_pending_show()}
            {#if expanded}
              <ChevronUp class="size-3.5" aria-hidden="true" />
            {:else}
              <ChevronDown class="size-3.5" aria-hidden="true" />
            {/if}
          {:else if bundleShown}
            {m.attachments_bundle_shown()}
            <Check class="size-3.5" aria-hidden="true" />
          {:else}
            {m.attachments_bundle_open()}
            <ArrowUpRight class="size-3.5" aria-hidden="true" />
          {/if}
        </span>
      </button>
      {#if !preview && expanded}
        {@render chips(documents)}
      {/if}
    {:else if documents.length > 0}
      {@render chips(documents)}
    {/if}
  </div>
{/if}
