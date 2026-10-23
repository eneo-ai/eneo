<!--
  What a conversation has to show in the panel, as one list: interactive tool
  views, documents created in the chat and uploaded files, the latter by the
  question they were sent with. The panel overview and the switcher in the
  panel's title both show it. It is the one full list of uploads; a message
  and the composer only summarise them and open this, a message's bundle at
  its own group.
-->
<script lang="ts">
  import { sanitizeLinkHref } from "$lib/components/markdown/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import { fileExtension } from "$lib/core/formatting/fileExtension";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import type { UploadGroup } from "$lib/features/chat/conversationUploads";
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
    focusGroup = null,
    onfile,
    onview
  }: {
    preview: FilePreview;
    documents: ConversationDocument[];
    uploads?: UploadGroup[];
    views?: PanelView[];
    fullHeight?: boolean;
    /** A section to scroll to and focus when the list opens, e.g. from a file bundle. */
    focusSection?: "uploads" | null;
    /** The upload group to scroll to and mark instead, by its key: the bundle's own files. */
    focusGroup?: string | null;
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

  const allUploads = $derived(uploads.flatMap((group) => group.files));
  // Files from more than one question are listed by the question; one
  // question's files need no grouping under the section heading.
  const grouped = $derived(uploads.length > 1);

  // A long upload list gets a filter: text on the name, and one type at a time.
  const FILTER_FROM = 8;
  let query = $state("");
  let selectedType = $state<string | null>(null);
  const filterable = $derived(allUploads.length > FILTER_FROM);
  const typeOf = (file: PreviewFile) => fileExtension(file.name) || m.unknown();
  const types = $derived.by(() => {
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- a tally, never rendered
    const counts = new Map<string, number>();
    for (const file of allUploads) counts.set(typeOf(file), (counts.get(typeOf(file)) ?? 0) + 1);
    return [...counts]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  });
  // Every group with a file that passes the filter, with the files that do.
  const shownGroups = $derived.by(() => {
    if (!filterable) return uploads.map((group) => ({ ...group, shown: group.files }));
    const needle = query.trim().toLowerCase();
    return uploads
      .map((group) => ({
        ...group,
        shown: group.files.filter(
          (file) =>
            (selectedType === null || typeOf(file) === selectedType) &&
            (!needle || displayName(file).toLowerCase().includes(needle))
        )
      }))
      .filter((group) => group.shown.length > 0);
  });
  const bytesOfAll = (files: PreviewFile[]) => files.reduce((sum, file) => sum + bytesOf(file), 0);
  const uploadsBytes = $derived(bytesOfAll(allUploads));

  // The group a message's bundle opened the list at: marked, and where the
  // list lands instead of the section heading.
  const markedGroup = $derived(
    grouped && uploads.some((group) => group.key === focusGroup) ? focusGroup : null
  );
  const groupDetail = (group: (typeof shownGroups)[number]) =>
    [
      group.shown.length < group.files.length
        ? m.conversation_uploads_group_matching({
            shown: group.shown.length,
            count: group.files.length
          })
        : group.files.length === 1
          ? m.conversation_uploads_group_files_one({ count: 1 })
          : m.conversation_uploads_group_files_other({ count: group.files.length }),
      bytesOfAll(group.files) > 0 ? formatBytes(bytesOfAll(group.files)) : ""
    ]
      .filter(Boolean)
      .join(" · ");

  // Opened on the uploads: the list scrolls there and the heading takes the
  // focus, after the panel's own focus handling has run. A marked group is
  // the destination instead; its heading lands at the top of the list.
  let uploadsHeading = $state<HTMLElement | null>(null);
  $effect(() => {
    const heading = uploadsHeading;
    if (focusSection !== "uploads" || markedGroup !== null || !heading) return;
    void tick().then(() => {
      heading.scrollIntoView({ block: "start" });
      heading.focus();
    });
  });
  const landOn = (heading: HTMLElement) => {
    void tick().then(() => {
      heading.scrollIntoView({ block: "start" });
      heading.focus();
    });
  };

  // A row is a ghost button on one line, with the hover of a row instead of
  // the button's; the one on show is marked as the selection.
  const rowClass =
    "hover:bg-hover-default h-9 min-w-0 flex-1 justify-start gap-2.5 px-2 py-1 text-left font-normal";
  const currentClass = "bg-accent-dimmer hover:bg-accent-dimmer";
  const pillClass =
    "aria-pressed:bg-accent-dimmer aria-pressed:text-accent-stronger h-6 px-2 text-xs font-normal tabular-nums aria-pressed:font-medium";
  // A group is a bordered block only while marked: the same accent outline as
  // the bundle that opened it, so the two read as one thing. The rows keep
  // their own selection.
  const groupClass = "rounded-lg border p-0.5 transition-colors";
  const markedClass =
    "border-accent-default motion-safe:animate-[upload-group-lit_1.2s_cubic-bezier(0.16,1,0.3,1)]";
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
        {m.conversation_documents_uploads()} · {allUploads.length}
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
              {m.conversation_uploads_filter_all({ count: allUploads.length })}
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
      {#if shownGroups.length === 0}
        <p class="text-muted-foreground px-2 py-1.5 text-xs">
          {m.conversation_uploads_filter_empty()}
        </p>
      {:else if grouped}
        {#each shownGroups as group (group.key)}
          {@const marked = group.key === markedGroup}
          <section
            aria-label={m.conversation_uploads_group({ ordinal: group.ordinal })}
            class={[groupClass, marked ? markedClass : "border-transparent"]}
          >
            <h4
              tabindex="-1"
              class="flex items-center gap-2 px-1.5 pt-1.5 pb-1 text-[11px] tabular-nums focus-visible:outline-none"
              {@attach (heading) => {
                if (marked) landOn(heading);
              }}
            >
              <span
                class={[
                  "shrink-0",
                  marked ? "text-accent-stronger font-medium" : "text-muted-foreground"
                ]}
              >
                {m.conversation_uploads_group({ ordinal: group.ordinal })}
                <span class="font-normal">· {groupDetail(group)}</span>
              </span>
              <span
                class={["h-px min-w-4 flex-1", marked ? "bg-accent-default/40" : "bg-border"]}
                aria-hidden="true"
              ></span>
            </h4>
            <ul class="flex flex-col">
              {#each group.shown as file (file.id)}
                {@render entry(file, [file])}
              {/each}
            </ul>
          </section>
        {/each}
      {:else}
        <ul class="flex flex-col">
          {#each shownGroups[0].shown as file (file.id)}
            {@render entry(file, [file])}
          {/each}
        </ul>
      {/if}
    </section>
  {/if}
</div>

<style>
  /* The marked group lights up once as the list lands on it, then settles
     into its outline: one motion, from the colour the bundle itself carries. */
  @keyframes -global-upload-group-lit {
    from {
      background-color: var(--accent-dimmer);
    }
    to {
      background-color: transparent;
    }
  }
</style>
