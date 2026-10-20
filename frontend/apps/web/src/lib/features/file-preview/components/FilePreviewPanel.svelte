<script lang="ts">
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { pickFileIcon } from "$lib/core/formatting/pickFileIcon";
  import { fileExtension } from "$lib/core/formatting/fileExtension";
  import { getAttachmentUrlService } from "$lib/features/attachments/AttachmentUrlService.svelte";
  import { m } from "$lib/paraglide/messages";
  import Check from "@lucide/svelte/icons/check";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Diff from "@lucide/svelte/icons/diff";
  import Download from "@lucide/svelte/icons/download";
  import FileText from "@lucide/svelte/icons/file-text";
  import History from "@lucide/svelte/icons/history";
  import Maximize2 from "@lucide/svelte/icons/maximize-2";
  import Minimize2 from "@lucide/svelte/icons/minimize-2";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";
  import X from "@lucide/svelte/icons/x";
  import { toast } from "svelte-sonner";
  import type { DocumentExport, DocumentSaver, FilePreview } from "../FilePreview.svelte";
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
    /** How a document is saved as a new version, for a document that can be; null for any other file. */
    saverOf?: (file: PreviewFile) => DocumentSaver | null;
    /** Everything the panel can show, for the switcher in the title. */
    contents?: PanelContents;
    /** Shown as a sheet over the conversation, where there is less room and nothing to maximise. */
    sheet?: boolean;
    onoverview?: () => void;
  };

  let {
    preview,
    versionsOf,
    exportOf,
    saverOf,
    contents,
    onoverview,
    sheet = false
  }: Props = $props();

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
  const extension = $derived(file ? fileExtension(file.name) : "");
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
  const detail = $derived.by(() => {
    if (draft || latest) return undefined;
    const size = `${extension}${bytes > 0 ? ` · ${formatBytes(bytes)}` : ""}`;
    return file?.revises_file_id ? `${size} · ${m.file_preview_edited_by_you()}` : size;
  });

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
  // A Markdown file names its images by their Eneo file; saved as it is, it
  // leaves Eneo without them.
  const namesImages = $derived(
    content?.kind === "markdown" && /!\[[^\]\n]*\]\(eneo-file:[0-9a-f]{32}/.test(content.text)
  );
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

  // The latest version of a Markdown document is edited in place. Edits stay
  // in the editor; one save makes one new version. While it is saved the
  // document is read-only: the version saved is the text as it stood when the
  // reader asked, and a keystroke meanwhile would be lost with the editor.
  const saver = $derived(file ? (saverOf?.(file) ?? null) : null);
  const saving = $derived(preview.saving);
  // Only the whole document can be edited: a preview cut short would be saved
  // as the whole document, and the part beyond the cut lost.
  const whole = $derived(content?.kind === "markdown" && !content.truncated);
  const editable = $derived(!!saver && !!file && whole && !draft && !later && !saving);
  // What this version changed against the one before it, when asked for.
  const comparable = $derived(!!earlier && content?.kind === "markdown" && !draft);
  let previousMarkdown = $state<string | null>(null);
  $effect(() => {
    const before = earlier;
    const wanted = comparable && preview.showChanges;
    previousMarkdown = null;
    if (!wanted || !before) return;
    let current = true;
    void preview.loadText(before).then((text) => {
      if (current) previousMarkdown = text;
    });
    return () => {
      current = false;
    };
  });
  // The content components by file, for the document text the reader has edited.
  let contentOf = $state<Record<string, FilePreviewContent>>({});

  /** Saves `markdown` as the document's next version; whether it was saved. */
  async function saveAs(target: DocumentSaver, markdown: string) {
    const request = preview.beginSave();
    try {
      const version = await target.save(markdown);
      request.apply(version, markdown);
      return true;
    } catch {
      toast.error(m.file_preview_save_failed());
      return false;
    } finally {
      request.finish();
    }
  }

  async function saveEdits() {
    const current = file;
    if (!current || !saver || !preview.dirty || saving) return;
    const markdown = contentOf[current.id]?.getMarkdown();
    if (markdown !== null && markdown !== undefined) await saveAs(saver, markdown);
  }

  // An older version is read, not edited; its text can be brought forward as
  // the newest version instead, as the reader's edit of the latest one.
  const restorer = $derived(latest ? (saverOf?.(latest) ?? null) : null);
  const restorable = $derived(!!restorer && whole && !draft);
  async function restoreVersion() {
    if (!restorer || !restorable || content?.kind !== "markdown" || saving) return;
    // The restored text is the text on show, so the panel looks the same
    // afterwards: the confirmation says what happened.
    const number = position + 1;
    if (await saveAs(restorer, content.text)) {
      toast.success(m.file_preview_version_restored({ number }));
    }
  }

  // Versions newest first, as the menu lists them.
  const versionRows = $derived(
    versions.map((version, index) => ({ version, number: index + 1 })).reverse()
  );
  const madeAt = (version: PreviewFile) =>
    version.created_at ? formatDateTime(version.created_at) : null;

  // The document row shows for a loaded file: its versions, its export, or
  // the save bar while edits are unsaved. A draft has none of these yet.
  const documentRow = $derived(!!file && !draft);

  /** The reader drops their edits: on the Cancel button, or agreeing to in the dialog. */
  function discardEdits() {
    if (file) contentOf[file.id]?.resetEditor();
    if (preview.pendingDiscard) preview.pendingDiscard.proceed();
    else preview.dropEdits();
  }
</script>

{#snippet versionMenu()}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button
          {...props}
          variant="ghost"
          size="sm"
          aria-label={m.file_preview_version_of({ current: position + 1, total: versions.length })}
        >
          <History aria-hidden="true" />
          <span class="tabular-nums">{position + 1} / {versions.length}</span>
          <ChevronDown class="size-3.5" aria-hidden="true" />
        </Button>
      {/snippet}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end" class="w-72">
      <DropdownMenu.Label>{m.file_preview_versions()}</DropdownMenu.Label>
      {#each versionRows as row (row.version.id)}
        <DropdownMenu.Item onSelect={() => preview.open(row.version)}>
          <span class="flex size-4 shrink-0 items-center justify-center" aria-hidden="true">
            {#if row.version.id === file?.id}<Check class="size-4" />{/if}
          </span>
          <span class="min-w-0 flex-1">
            {m.file_preview_version_number({ number: row.number })}
            <span class="text-muted-foreground block text-xs whitespace-normal">
              {row.version.revises_file_id
                ? m.file_preview_edited_by_you()
                : m.file_preview_version_by_assistant()}{madeAt(row.version)
                ? ` · ${madeAt(row.version)}`
                : ""}
            </span>
          </span>
        </DropdownMenu.Item>
      {/each}
    </DropdownMenu.Content>
  </DropdownMenu.Root>
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
          <span class="min-w-0 flex-1">
            {FORMATS.md.name}
            {#if namesImages}
              <span class="text-muted-foreground block text-xs whitespace-normal"
                >{m.file_preview_export_markdown_without_images()}</span
              >
            {/if}
          </span>
          <span class="text-muted-foreground text-xs">{FORMATS.md.ending}</span>
        </DropdownMenu.Item>
        {#each ["docx", "pdf"] as const as format (format)}
          <DropdownMenu.Item
            disabled={!availability?.[format].available || availabilityLoading}
            onSelect={() => exportAs(format)}
          >
            <span class="min-w-0 flex-1">
              {FORMATS[format].name}
              {#if availability && !availability[format].available}
                <span class="text-muted-foreground block text-xs whitespace-normal"
                  >{unavailableReason(availability[format].reason)}</span
                >
              {:else if availability?.template}
                <!-- The organisation's document template the file is rendered into. -->
                <span class="text-muted-foreground block text-xs whitespace-normal"
                  >{m.file_preview_export_template({
                    name:
                      availability.template.source === "builtin"
                        ? m.document_template_builtin_name()
                        : availability.template.name
                  })}</span
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

<!-- The header holds navigation and identity, so the title keeps its width
     whatever the document can do, and the header stays the height of the
     overview's. The document row beneath holds what applies to the document:
     its versions and export, or, while there are unsaved edits, the save bar
     in their place. -->
<header
  class={[
    "border-border flex min-h-16 shrink-0 items-center gap-3 px-4 py-3",
    !documentRow && "border-b"
  ]}
>
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
        <span class="truncate"
          >{file?.revises_file_id
            ? m.file_preview_older_version_edited_by_you()
            : m.file_preview_older_version()}</span
        >
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
</header>
{#if documentRow}
  {#if preview.dirty}
    <div
      class="border-border bg-muted flex shrink-0 items-center justify-between gap-2 border-b py-1.5 pr-3 pl-4"
      role="status"
    >
      <span class="text-muted-foreground flex min-w-0 items-center gap-2 text-sm">
        <span class="bg-warning-default size-2 shrink-0 rounded-full" aria-hidden="true"></span>
        <span class="truncate">{m.file_preview_unsaved_changes()}</span>
      </span>
      <span class="flex shrink-0 items-center gap-1">
        <Button variant="ghost" size="sm" disabled={saving} onclick={discardEdits}>
          {m.cancel()}
        </Button>
        <Button size="sm" disabled={saving} onclick={saveEdits}>
          {saving ? m.file_preview_saving() : m.save()}
        </Button>
      </span>
    </div>
  {:else}
    <div
      class="border-border flex shrink-0 items-center justify-between gap-2 border-b py-1.5 pr-3 pl-3"
    >
      <!-- What applies to the version on show stands beside its menu: the
           change marks for one with a version before it, and bringing an
           older one forward as the newest. -->
      <span class="flex min-w-0 items-center gap-1">
        {#if versions.length > 1}
          {@render versionMenu()}
        {/if}
        {#if comparable}
          <Button
            variant="ghost"
            size="icon-sm"
            class="aria-pressed:bg-accent-dimmer aria-pressed:text-accent-stronger"
            aria-pressed={preview.showChanges}
            aria-label={m.file_preview_show_changes()}
            title={m.file_preview_show_changes()}
            onclick={() => (preview.showChanges = !preview.showChanges)}
          >
            <Diff aria-hidden="true" />
          </Button>
        {/if}
        {#if restorable}
          <Button
            variant="outline"
            size="sm"
            disabled={saving}
            aria-label={m.file_preview_restore_version()}
            title={m.file_preview_restore_version()}
            onclick={restoreVersion}
          >
            <RotateCcw aria-hidden="true" />
            {m.file_preview_restore()}
          </Button>
        {/if}
      </span>
      <span class="flex shrink-0 items-center gap-1">
        {@render exportMenu()}
      </span>
    </div>
  {/if}
{/if}

{#if updating}
  <div class="border-border shrink-0 border-b px-4 py-2 text-sm" role="status">
    {#if preview.replacementError}
      <p>{m.file_preview_update_failed()}</p>
      <Button variant="outline" size="sm" class="mt-2" onclick={() => preview.retry()}
        >{m.retry()}</Button
      >
    {:else if preview.dirty && preview.replacementContent}
      <!-- The newer version waits until the reader is done with their edits. -->
      <p class="text-muted-foreground text-xs">{m.file_preview_newer_version_while_editing()}</p>
      <Button variant="outline" size="sm" class="mt-2" onclick={discardEdits}>
        {m.file_preview_show_latest()}
      </Button>
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
          bind:this={contentOf[view.file.id]}
          content={view.content}
          title={view.file.name}
          highlight={view.pending ? null : highlight}
          editable={!view.pending && editable}
          edits={view.pending ? null : preview.editsOf(view.file)}
          previousMarkdown={view.pending ? null : previousMarkdown}
          onready={() => preview.finishReplacement(view.file.id)}
          onerror={() => preview.failReplacement(view.file.id)}
          onquote={(text, locator) => preview.quoteSelection(text, locator)}
          onchange={(text) => preview.setEdits(view.file.id, text)}
          onsave={saveEdits}
        />
      </div>
    {/each}
  {/if}
</div>

<AlertDialog.Root
  open={preview.pendingDiscard !== null}
  onOpenChange={(open) => {
    if (!open) preview.keepEditing();
  }}
>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.file_preview_discard_edits_title()}</AlertDialog.Title>
      <AlertDialog.Description>{m.file_preview_discard_edits_description()}</AlertDialog.Description
      >
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel onclick={() => preview.keepEditing()}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action onclick={discardEdits}
        >{m.file_preview_discard_edits()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
