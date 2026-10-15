<!--
  What a conversation has to show in the panel, as one list: interactive tool
  views, documents created in the chat and uploaded files. The panel
  overview and the switcher in the panel's title both show it. It is the one
  full list of uploads; a message and the composer only summarise them and
  open this.
-->
<script lang="ts">
  import { sanitizeLinkHref } from "$lib/components/markdown/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import { fileExtension } from "$lib/core/formatting/fileExtension";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import type { ConversationDocument } from "$lib/features/chat/documentVersions";
  import { m } from "$lib/paraglide/messages";
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Check from "@lucide/svelte/icons/check";
  import Download from "@lucide/svelte/icons/download";
  import Search from "@lucide/svelte/icons/search";
  import { tick } from "svelte";
  import type { FilePreview } from "../FilePreview.svelte";
  import type { PanelView } from "../panelContents";
  import { previewKindOf, type PreviewFile } from "../previewKind";

  let {
    preview,
    documents,
    uploads = [],
    views = [],
    fullHeight = false,
    focusSection = null,
    onfile,
    onview
  }: {
    preview: FilePreview;
    documents: ConversationDocument[];
    uploads?: PreviewFile[];
    views?: PanelView[];
    fullHeight?: boolean;
    /** A section to scroll to and focus when the list opens, e.g. from a file bundle. */
    focusSection?: "uploads" | null;
    onfile: (file: PreviewFile) => void;
    onview?: (view: PanelView) => void;
  } = $props();

  const attachmentUrls = getAttachmentUrlService();

  // A Markdown document is read in Eneo and listed by its title.
  const displayName = (file: { name: string; mimetype: string }) =>
    previewKindOf(file) === "markdown" ? file.name.replace(/\.(md|markdown)$/i, "") : file.name;
  const bytesOf = (file: PreviewFile) => file.original_size ?? file.size;
  const description = (latest: PreviewFile, versionCount: number) => {
    const bytes = bytesOf(latest);
    return [
      fileExtension(latest.name),
      bytes > 0 ? formatBytes(bytes) : "",
      versionCount > 1 ? m.conversation_document_versions({ count: versionCount }) : ""
    ]
      .filter(Boolean)
      .join(" · ");
  };

  // A long upload list gets a filter: text on the name, and one type at a time.
  const FILTER_FROM = 8;
  let query = $state("");
  let selectedType = $state<string | null>(null);
  const filterable = $derived(uploads.length > FILTER_FROM);
  const typeOf = (file: PreviewFile) => fileExtension(file.name) || m.unknown();
  const types = $derived.by(() => {
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- a tally, never rendered
    const counts = new Map<string, number>();
    for (const file of uploads) counts.set(typeOf(file), (counts.get(typeOf(file)) ?? 0) + 1);
    return [...counts]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  });
  const shownUploads = $derived.by(() => {
    if (!filterable) return uploads;
    const needle = query.trim().toLowerCase();
    return uploads.filter(
      (file) =>
        (selectedType === null || typeOf(file) === selectedType) &&
        (!needle || displayName(file).toLowerCase().includes(needle))
    );
  });
  const uploadsBytes = $derived(uploads.reduce((sum, file) => sum + bytesOf(file), 0));

  // Opened on the uploads: the list scrolls there and the heading takes the
  // focus, after the panel's own focus handling has run.
  let uploadsHeading = $state<HTMLElement | null>(null);
  $effect(() => {
    const heading = uploadsHeading;
    if (focusSection !== "uploads" || !heading) return;
    void tick().then(() => {
      heading.scrollIntoView({ block: "start" });
      heading.focus();
    });
  });

  // A row is a ghost button on one line, with the hover of a row instead of
  // the button's; the one on show is marked as the selection.
  const rowClass =
    "hover:bg-hover-default h-9 min-w-0 flex-1 justify-start gap-2.5 px-2 py-1 text-left font-normal";
  const currentClass = "bg-accent-dimmer hover:bg-accent-dimmer";
  const pillClass =
    "aria-pressed:bg-accent-dimmer aria-pressed:text-accent-stronger h-6 px-2 text-xs font-normal tabular-nums aria-pressed:font-medium";
</script>

{#snippet row(Icon: typeof AppWindow, name: string, detail: string, current: boolean)}
  <span
    class={[
      "text-accent-stronger flex size-6 shrink-0 items-center justify-center rounded-md",
      current ? "bg-background" : "bg-accent-dimmer"
    ]}
  >
    <Icon class="size-3.5" aria-hidden="true" />
  </span>
  <span class="text-foreground min-w-0 flex-1 truncate text-[13px] font-medium">{name}</span>
  {#if detail}
    <span class="text-muted-foreground shrink-0 text-[11.5px] tabular-nums">{detail}</span>
  {/if}
  {#if current}
    <Check class="text-accent-stronger size-4 shrink-0" aria-hidden="true" />
  {/if}
{/snippet}

<!-- `versions` are every file of the entry; the panel may show an earlier one. -->
{#snippet entry(file: PreviewFile, versions: PreviewFile[])}
  {@const href = sanitizeLinkHref(attachmentUrls.getOriginalUrl(file) ?? null)}
  {@const current = versions.some((version) => preview.isOpen(version))}
  {@const Icon = pickFileIcon(file.mimetype)}
  <li class="group flex items-center gap-1">
    {#if preview.canPreview(file)}
      <Button
        variant="ghost"
        class={[rowClass, current && currentClass]}
        aria-label={m.file_preview_open({ name: file.name })}
        aria-current={current ? "true" : undefined}
        onclick={() => onfile(file)}
      >
        {@render row(Icon, displayName(file), description(file, versions.length), current)}
      </Button>
    {:else}
      <div class="flex h-9 min-w-0 flex-1 items-center gap-2.5 px-2 py-1">
        {@render row(Icon, displayName(file), description(file, versions.length), false)}
      </div>
    {/if}
    <Button
      variant="ghost"
      size="icon-sm"
      class="hover:bg-hover-default opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
      {href}
      download={file.name}
      disabled={!href}
      aria-label={m.generated_file_download({ name: file.name })}
      title={m.download()}
    >
      <Download aria-hidden="true" />
    </Button>
  </li>
{/snippet}

{#snippet heading(text: string, count: number)}
  <h3 class="text-muted-foreground px-2 pt-2 pb-1 text-xs font-medium tabular-nums">
    {text} · {count}
  </h3>
{/snippet}

<div class={["p-1", !fullHeight && "max-h-80 overflow-y-auto"]}>
  {#if views.length > 0}
    <section aria-label={m.conversation_documents_views()}>
      {@render heading(m.conversation_documents_views(), views.length)}
      <ul class="flex flex-col">
        {#each views as view (view.id)}
          <li class="flex">
            <Button
              variant="ghost"
              class={[rowClass, view.shown && currentClass]}
              aria-current={view.shown ? "true" : undefined}
              onclick={() => onview?.(view)}
            >
              <!-- A view that says what it is about is listed by that, above its tool. -->
              {@render row(
                AppWindow,
                view.subject ?? view.title,
                view.subject ? view.title : m.mcp_app_view_title(),
                view.shown
              )}
            </Button>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
  {#if documents.length > 0}
    <section aria-label={m.conversation_documents_created()}>
      {@render heading(m.conversation_documents_created(), documents.length)}
      <ul class="flex flex-col">
        {#each documents as document (document.latest.id)}
          {@render entry(document.latest, document.versions)}
        {/each}
      </ul>
    </section>
  {/if}
  {#if uploads.length > 0}
    <section aria-label={m.conversation_documents_uploads()}>
      <h3
        bind:this={uploadsHeading}
        tabindex="-1"
        class="text-muted-foreground px-2 pt-2 pb-1 text-xs font-medium tabular-nums focus-visible:outline-none"
      >
        {m.conversation_documents_uploads()} · {uploads.length}
        {#if uploadsBytes > 0}
          · {formatBytes(uploadsBytes)}
        {/if}
      </h3>
      {#if filterable}
        <div class="flex flex-col gap-1.5 px-1 pb-1.5">
          <InputGroup.Root class="bg-background">
            <InputGroup.Addon>
              <Search class="size-4 shrink-0 opacity-60" aria-hidden="true" />
            </InputGroup.Addon>
            <InputGroup.Input
              type="search"
              bind:value={query}
              placeholder={m.conversation_uploads_filter()}
              aria-label={m.conversation_uploads_filter()}
              autocomplete="off"
            />
          </InputGroup.Root>
          <div class="flex flex-wrap gap-1">
            <Button
              variant="ghost"
              size="xs"
              class={pillClass}
              aria-pressed={selectedType === null}
              onclick={() => (selectedType = null)}
            >
              {m.conversation_uploads_filter_all({ count: uploads.length })}
            </Button>
            {#each types as type (type.name)}
              <Button
                variant="ghost"
                size="xs"
                class={pillClass}
                aria-pressed={selectedType === type.name}
                onclick={() => (selectedType = selectedType === type.name ? null : type.name)}
              >
                {type.name}
                {type.count}
              </Button>
            {/each}
          </div>
        </div>
      {/if}
      {#if shownUploads.length > 0}
        <ul class="flex flex-col">
          {#each shownUploads as file (file.id)}
            {@render entry(file, [file])}
          {/each}
        </ul>
      {:else}
        <p class="text-muted-foreground px-2 py-1.5 text-xs">
          {m.conversation_uploads_filter_empty()}
        </p>
      {/if}
    </section>
  {/if}
</div>
