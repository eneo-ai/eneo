<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { m } from "$lib/paraglide/messages";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import ChevronLeft from "@lucide/svelte/icons/chevron-left";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Download from "@lucide/svelte/icons/download";
  import FileText from "@lucide/svelte/icons/file-text";
  import Maximize2 from "@lucide/svelte/icons/maximize-2";
  import Minimize2 from "@lucide/svelte/icons/minimize-2";
  import X from "@lucide/svelte/icons/x";
  import { toast } from "svelte-sonner";
  import type { DocumentExport, FilePreview } from "../FilePreview.svelte";
  import type { PanelContents } from "../panelContents";
  import { previewKindOf, type PreviewFile } from "../previewKind";
  import DraftPreview from "./DraftPreview.svelte";
  import FilePreviewContent from "./FilePreviewContent.svelte";
  import PanelBackButton from "./PanelBackButton.svelte";
  import PanelTitle from "./PanelTitle.svelte";

  type Props = {
    preview: FilePreview;
    /** Every version of the document a file belongs to, oldest first. */
    versionsOf?: (file: PreviewFile) => PreviewFile[];
    /** How a file is exported, for a document that can be; null for any other file. */
    exportOf?: (file: PreviewFile) => DocumentExport | null;
    /** Everything the panel can show, for the switcher in the title. */
    contents?: PanelContents;
    /** Shown as a sheet over the conversation, where there is less room and nothing to maximise. */
    sheet?: boolean;
    onoverview?: () => void;
  };

  let { preview, versionsOf, exportOf, contents, onoverview, sheet = false }: Props = $props();

  const attachmentUrls = getAttachmentUrlService();

  // Keep the existing renderer mounted while its replacement is prepared.
  const keepingFile = $derived(!!preview.file && !!preview.content && preview.status === "ready");
  const draft = $derived(keepingFile ? null : preview.draft);
  const updating = $derived(keepingFile && (!!preview.draft || !!preview.replacementFile));
  const nextTitle = $derived(
    preview.replacementFile?.name || preview.draft?.title || m.file_preview_untitled_document()
  );
  const file = $derived(draft ? null : preview.file);

  const Icon = $derived(file ? pickFileIcon(file.mimetype) : FileText);
  // The downloaded file's size; `size` counts the extracted text of a document.
  const bytes = $derived(file ? (file.original_size ?? file.size) : 0);
  const extension = $derived(
    file?.name.includes(".") ? (file.name.split(".").pop() ?? "").toUpperCase() : ""
  );
  // A Markdown document is read in Eneo and headed by its title, as it was
  // while it was written.
  const title = $derived.by(() => {
    if (draft) return draft.title || m.file_preview_untitled_document();
    if (!file) return "";
    return previewKindOf(file) === "markdown"
      ? file.name.replace(/\.(md|markdown)$/i, "")
      : file.name;
  });
  const downloadUrl = $derived(file ? attachmentUrls.getOriginalUrl(file) : undefined);

  // The versions of the document on show, and where this one stands among them.
  const versions = $derived(file ? (versionsOf?.(file) ?? []) : []);
  const position = $derived(versions.findIndex((version) => version.id === file?.id));
  const earlier = $derived(position > 0 ? versions[position - 1] : null);
  const later = $derived(
    position >= 0 && position < versions.length - 1 ? versions[position + 1] : null
  );
  const latest = $derived(later ? versions[versions.length - 1] : null);
  // The type and size under the title; a draft and an older version say
  // something else there.
  const detail = $derived(
    draft || latest ? undefined : `${extension}${bytes > 0 ? ` · ${formatBytes(bytes)}` : ""}`
  );

  const exporting = $derived(file ? (exportOf?.(file) ?? null) : null);
  let busy = $state<"docx" | "pdf" | null>(null);
  let exportOpen = $state(false);
  let availability = $state<Awaited<ReturnType<DocumentExport["availability"]>> | null>(null);
  let availabilityLoading = $state(false);
  let availabilityFailed = $state(false);
  let retryAvailability = $state(0);

  // Recheck on every menu opening and document/version change. A stale request
  // must never enable formats for the next document.
  $effect(() => {
    const target = exporting;
    const id = file?.id;
    const open = exportOpen;
    void retryAvailability;
    availability = null;
    availabilityFailed = false;
    availabilityLoading = false;
    if (!open || !target || !id) return;
    let current = true;
    availabilityLoading = true;
    target
      .availability()
      .then(
        (result) => {
          if (current) availability = result;
        },
        () => {
          if (current) availabilityFailed = true;
        }
      )
      .finally(() => {
        if (current) availabilityLoading = false;
      });
    return () => {
      current = false;
    };
  });

  function unavailableReason(reason: string | null | undefined) {
    if (reason === "format_unsupported") return m.file_preview_export_format_unsupported();
    if (reason === "document_unsupported") return m.file_preview_export_document_unsupported();
    if (reason === "incompatible_tool") return m.file_preview_export_incompatible();
    return m.file_preview_export_unavailable();
  }

  // Product names of the formats; the same in every language.
  const FORMATS = {
    md: { name: "Markdown", ending: ".md" },
    docx: { name: "Word", ending: ".docx" },
    pdf: { name: "PDF", ending: ".pdf" }
  };

  /** Hands a file to the browser to save under `name`. */
  function save(url: string, name: string) {
    Object.assign(document.createElement("a"), { href: url, download: name }).click();
  }

  function saveOriginal() {
    if (file && downloadUrl) save(downloadUrl, file.name);
  }

  async function exportAs(format: "docx" | "pdf") {
    if (!file || !exporting || busy) return;
    busy = format;
    try {
      const blob = await exporting.exportAs(format);
      // The exported file exists only in this page.
      const url = URL.createObjectURL(blob);
      save(url, `${title}${FORMATS[format].ending}`);
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch {
      toast.error(m.file_preview_export_failed());
    } finally {
      busy = null;
    }
  }

  const content = $derived(preview.content);
  const views = $derived(
    file && content && preview.status === "ready"
      ? [
          { file, content, pending: false },
          ...(preview.replacementFile && preview.replacementContent
            ? [
                {
                  file: preview.replacementFile,
                  content: preview.replacementContent,
                  pending: true
                }
              ]
            : [])
        ]
      : []
  );
  // What to mark in the file: a quote the user asked to see in place, else the
  // quote waiting in the composer, so it stays visible while the question is written.
  const highlight = $derived(
    preview.highlight ?? (preview.quote?.fileId === file?.id ? preview.quote : null)
  );
</script>

{#snippet versionButtons()}
  <Button
    variant="ghost"
    size="icon-sm"
    disabled={!earlier}
    aria-label={m.file_preview_previous_version()}
    title={m.file_preview_previous_version()}
    onclick={() => earlier && preview.open(earlier)}
  >
    <ChevronLeft aria-hidden="true" />
  </Button>
  {#if !sheet}
    <span class="text-muted-foreground min-w-9 text-center text-xs tabular-nums">
      {position + 1} / {versions.length}
    </span>
  {/if}
  <Button
    variant="ghost"
    size="icon-sm"
    disabled={!later}
    aria-label={m.file_preview_next_version()}
    title={m.file_preview_next_version()}
    onclick={() => later && preview.open(later)}
  >
    <ChevronRight aria-hidden="true" />
  </Button>
{/snippet}

{#snippet exportMenu()}
  {#if file && exporting}
    <DropdownMenu.Root bind:open={exportOpen}>
      <DropdownMenu.Trigger>
        {#snippet child({ props })}
          {#if sheet}
            <Button
              {...props}
              variant="ghost"
              size="icon-sm"
              disabled={busy !== null}
              aria-label={m.file_preview_export()}
              title={m.file_preview_export()}
            >
              <Download aria-hidden="true" />
            </Button>
          {:else}
            <Button {...props} variant="outline" size="sm" disabled={busy !== null}>
              <Download aria-hidden="true" />
              {busy ? m.file_preview_exporting() : m.file_preview_export()}
              <ChevronDown class="size-3.5" aria-hidden="true" />
            </Button>
          {/if}
        {/snippet}
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end" class="w-64">
        <DropdownMenu.Item onSelect={saveOriginal}>
          <span class="flex-1">{FORMATS.md.name}</span>
          <span class="text-muted-foreground text-xs">{FORMATS.md.ending}</span>
        </DropdownMenu.Item>
        {#each ["docx", "pdf"] as const as format (format)}
          <DropdownMenu.Item
            disabled={!availability?.[format].available || availabilityLoading}
            onSelect={() => exportAs(format)}
          >
            <span class="flex-1">
              {FORMATS[format].name}
              {#if availability && !availability[format].available}
                <span class="text-muted-foreground block text-xs"
                  >{unavailableReason(availability[format].reason)}</span
                >
              {/if}
            </span>
            <span class="text-muted-foreground text-xs">{FORMATS[format].ending}</span>
          </DropdownMenu.Item>
        {/each}
        {#if availabilityLoading}
          <p class="text-muted-foreground px-2 py-1.5 text-xs" role="status">{m.loading()}</p>
        {:else if availabilityFailed}
          <p class="text-muted-foreground px-2 py-1.5 text-xs" role="status">
            {m.file_preview_export_check_failed()}
          </p>
          <DropdownMenu.Item
            onSelect={(event) => {
              event.preventDefault();
              retryAvailability++;
            }}
          >
            {m.retry()}
          </DropdownMenu.Item>
        {/if}
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  {:else if file}
    <Button
      variant="ghost"
      size="icon-sm"
      href={downloadUrl}
      download={file.name}
      disabled={!downloadUrl}
      aria-label={m.generated_file_download({ name: file.name })}
      title={m.download()}
    >
      <Download aria-hidden="true" />
    </Button>
  {/if}
{/snippet}

<header class="border-border flex min-h-16 shrink-0 flex-col border-b">
  <div class="flex flex-1 items-center gap-3 px-4 py-3">
    {#if onoverview}
      <PanelBackButton onclick={onoverview} />
    {/if}
    <span
      class="bg-accent-dimmer text-accent-stronger flex size-8 shrink-0 items-center justify-center rounded-md"
    >
      <Icon class="size-4" aria-hidden="true" />
    </span>
    <div class="flex min-w-0 flex-1 flex-col leading-tight">
      <PanelTitle {title} {detail} {preview} {contents} />
      {#if draft}
        <p class="text-accent-stronger flex items-center gap-1.5 text-xs" role="status">
          <span class="bg-accent-default size-1.5 shrink-0 rounded-full" aria-hidden="true"></span>
          {m.file_preview_writing()}
        </p>
      {:else if latest}
        <p class="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs">
          <span class="truncate">{m.file_preview_older_version()}</span>
          <button
            type="button"
            class="text-accent-stronger focus-visible:ring-accent-default shrink-0 rounded-sm font-medium underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
            onclick={() => latest && preview.open(latest)}
          >
            {m.file_preview_show_latest()}
          </button>
        </p>
      {/if}
    </div>
    {#if versions.length > 1 && !sheet}
      <div
        role="group"
        aria-label={m.file_preview_versions()}
        class="flex shrink-0 items-center gap-0.5"
      >
        {@render versionButtons()}
      </div>
    {/if}
    {@render exportMenu()}
    {#if !sheet}
      <Button
        variant="ghost"
        size="icon-sm"
        aria-pressed={preview.maximised}
        aria-label={preview.maximised ? m.file_preview_restore_size() : m.file_preview_maximise()}
        title={preview.maximised ? m.file_preview_restore_size() : m.file_preview_maximise()}
        onclick={() => (preview.maximised = !preview.maximised)}
      >
        {#if preview.maximised}
          <Minimize2 aria-hidden="true" />
        {:else}
          <Maximize2 aria-hidden="true" />
        {/if}
      </Button>
    {/if}
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={m.close()}
      title={m.close()}
      onclick={() => preview.close()}
    >
      <X aria-hidden="true" />
    </Button>
  </div>
  {#if versions.length > 1 && sheet}
    <!-- On a narrow screen the versions get a row of their own. -->
    <div
      role="group"
      aria-label={m.file_preview_versions()}
      class="border-border flex items-center justify-between border-t px-4 py-1.5"
    >
      <span class="text-muted-foreground text-xs tabular-nums">
        {m.file_preview_version_of({ current: position + 1, total: versions.length })}
      </span>
      <div class="flex items-center gap-0.5">
        {@render versionButtons()}
      </div>
    </div>
  {/if}
</header>

{#if updating}
  <div class="border-border shrink-0 border-b px-4 py-2 text-sm" role="status">
    {#if preview.replacementError}
      <p>{m.file_preview_update_failed()}</p>
      <Button variant="outline" size="sm" class="mt-2" onclick={() => preview.retry()}
        >{m.retry()}</Button
      >
    {:else}
      <p class="text-accent-stronger font-medium">{m.file_preview_updating({ name: nextTitle })}</p>
      <p class="text-muted-foreground text-xs">{m.file_preview_keep_current()}</p>
    {/if}
  </div>
{/if}

<div class="relative flex min-h-0 flex-1 flex-col">
  {#if draft}
    <DraftPreview {draft} />
  {:else if !file}
    <!-- Nothing to show: the layout closes the panel. -->
  {:else if preview.status === "loading"}
    <p class="text-muted-foreground p-6 text-sm" role="status">{m.file_preview_loading()}</p>
  {:else if preview.status === "too_large"}
    <p class="text-muted-foreground p-6 text-sm">{m.file_preview_too_large()}</p>
  {:else if preview.status === "failed" || !content}
    <div class="flex flex-col items-start gap-3 p-6">
      <p class="text-muted-foreground text-sm">{m.file_preview_failed()}</p>
      <Button variant="outline" size="sm" onclick={() => preview.retry()}>{m.retry()}</Button>
    </div>
  {:else}
    <!-- The content holds per-file state (the active sheet, a rendered frame,
         the selection). -->
    {#each views as view (view.file.id)}
      <div
        class="absolute inset-0 flex min-h-0 flex-col"
        class:invisible={view.pending}
        inert={view.pending}
        aria-hidden={view.pending ? "true" : undefined}
      >
        <FilePreviewContent
          content={view.content}
          title={view.file.name}
          highlight={view.pending ? null : highlight}
          onready={() => preview.finishReplacement(view.file.id)}
          onerror={() => preview.failReplacement(view.file.id)}
          onquote={(text, locator) => preview.quoteSelection(text, locator)}
        />
      </div>
    {/each}
  {/if}
</div>
