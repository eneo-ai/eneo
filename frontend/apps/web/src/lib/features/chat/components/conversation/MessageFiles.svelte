<script lang="ts">
  import { getMessageContext } from "../../MessageContext.svelte";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import AsyncImage from "$lib/components/AsyncImage.svelte";
  import { m } from "$lib/paraglide/messages";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";

  const attachmentUrlService = getAttachmentUrlService();
  const { current } = getMessageContext();

  const allFiles = $derived.by(() =>
    current().files.map((file) => {
      const parts = file.name.split(".");
      const extension = parts.length > 1 ? parts[parts.length - 1].toUpperCase() : "";
      const isImage = file.mimetype.includes("image");
      return {
        id: file.id,
        name: file.name,
        type: isImage ? ("image" as const) : ("generic" as const),
        url: isImage ? (attachmentUrlService.getUrl(file) ?? null) : null,
        extension,
        mimetype: file.mimetype,
        size: file.size
      };
    })
  );

  const images = $derived(allFiles.filter((f) => f.type === "image"));
  const documents = $derived(allFiles.filter((f) => f.type === "generic"));

  // Collapse threshold: anything over 4 documents is summarised so a long
  // upload list (e.g. 40+ policy files) doesn't stretch the chat vertically.
  const COLLAPSED_VISIBLE = 3;
  const COLLAPSE_THRESHOLD = 4;
  let isExpanded = $state(false);

  const visibleDocuments = $derived(
    isExpanded || documents.length <= COLLAPSE_THRESHOLD
      ? documents
      : documents.slice(0, COLLAPSED_VISIBLE)
  );
  const overflowCount = $derived(documents.length - COLLAPSED_VISIBLE);
  const showOverflowButton = $derived(!isExpanded && documents.length > COLLAPSE_THRESHOLD);
</script>

{#if allFiles.length > 0}
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

    {#if documents.length > 0}
      <div class="grid w-full max-w-[42rem] grid-cols-1 gap-2 sm:grid-cols-2">
        {#each visibleDocuments as file (file.id)}
          {@const Icon = pickFileIcon(file.mimetype)}
          <div
            class="group border-default bg-primary flex h-11 min-w-0 items-center gap-2 rounded-lg border py-1.5 pr-2 pl-1.5 shadow-sm"
            title={file.name}
          >
            <div
              class="bg-accent-dimmer text-accent-stronger flex size-8 flex-shrink-0 items-center justify-center rounded-md"
            >
              <Icon class="size-4" aria-hidden="true" />
            </div>
            <div class="flex min-w-0 flex-1 flex-col leading-tight">
              <span class="text-default truncate text-sm font-medium">{file.name}</span>
              <span class="text-tertiary truncate text-[11px] tabular-nums">
                {file.extension}{file.size > 0 ? ` · ${formatBytes(file.size)}` : ""}
              </span>
            </div>
          </div>
        {/each}

        {#if showOverflowButton}
          <button
            type="button"
            onclick={() => (isExpanded = true)}
            class="border-default bg-primary hover:bg-secondary hover:border-stronger text-default flex h-11 items-center justify-center rounded-lg border text-sm font-medium shadow-sm transition-colors"
          >
            {m.attachments_show_more({ count: overflowCount })}
          </button>
        {/if}
      </div>

      {#if isExpanded && documents.length > COLLAPSE_THRESHOLD}
        <button
          type="button"
          onclick={() => (isExpanded = false)}
          class="text-tertiary hover:text-default text-xs transition-colors"
        >
          {m.attachments_show_less()}
        </button>
      {/if}
    {/if}
  </div>
{/if}
