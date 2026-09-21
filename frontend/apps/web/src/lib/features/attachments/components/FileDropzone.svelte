<!--
    Drop area for picking local files: drag and drop (including folders),
    a file picker, an inline summary of what the server accepts and,
    with `keepSelection`, the list of picked files. Files whose type is
    not accepted never enter the selection; every pick is reported through
    `onselect` so the caller can queue the accepted files and explain the
    rejected ones.
-->
<script lang="ts">
  import CloudUploadIcon from "@lucide/svelte/icons/cloud-upload";
  import FileIcon from "@lucide/svelte/icons/file";
  import FilePlusIcon from "@lucide/svelte/icons/file-plus";
  import Trash2Icon from "@lucide/svelte/icons/trash-2";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";
  import type { AcceptedFormat } from "../AttachmentManager";
  import { summarizeFileFormats, type FileFormatGroupKind } from "../fileFormatSummary";

  export type FileSelection = { accepted: File[]; rejected: File[] };

  type Props = {
    files?: File[];
    formats: readonly AcceptedFormat[];
    name?: string;
    disabled?: boolean;
    multiple?: boolean;
    /** Keep picked files in the list below the drop prompt (false: only report them). */
    keepSelection?: boolean;
    description?: string;
    class?: string;
    onselect?: (selection: FileSelection) => void;
  };

  let {
    files = $bindable([]),
    formats,
    name = "dropzoneInput",
    disabled = false,
    multiple = true,
    keepSelection = true,
    description,
    class: className,
    onselect
  }: Props = $props();

  const groupLabels: Record<FileFormatGroupKind, () => string> = {
    documents: m.file_format_group_documents,
    images: m.file_format_group_images,
    audio: m.file_format_group_audio,
    other: m.file_format_group_other
  };

  const acceptedMimeTypes = $derived(formats.map((format) => format.mimetype));
  const groups = $derived(summarizeFileFormats(formats));
  const formatsHeadingId = $props.id();

  let input = $state<HTMLInputElement | null>(null);
  let isDragging = $state(false);
  // dragenter/dragleave fire for every child element crossed, so count the
  // nesting depth instead of trusting a single leave event.
  let dragDepth = 0;

  function openPicker() {
    if (!disabled) input?.click();
  }

  function handleInputChange() {
    if (!input) return;
    addFiles([...(input.files ?? [])]);
    // Clear so picking the same file again still fires `change`.
    input.value = "";
  }

  function handleDragEnter(event: DragEvent) {
    event.preventDefault();
    dragDepth += 1;
    isDragging = !disabled;
  }

  function handleDragOver(event: DragEvent) {
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = disabled ? "none" : "copy";
    }
  }

  function handleDragLeave(event: DragEvent) {
    event.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) isDragging = false;
  }

  async function handleDrop(event: DragEvent) {
    event.preventDefault();
    dragDepth = 0;
    isDragging = false;
    if (disabled || !event.dataTransfer) return;
    addFiles(await collectDroppedFiles(event.dataTransfer));
  }

  async function collectDroppedFiles(dataTransfer: DataTransfer): Promise<File[]> {
    // Entries must be grabbed synchronously: the DataTransfer is emptied once
    // the drop handler yields.
    const entries = [...dataTransfer.items].map((item) => item.webkitGetAsEntry?.() ?? null);
    if (entries.every((entry) => entry === null)) {
      return [...dataTransfer.files];
    }
    const collected: File[] = [];
    for (const entry of entries) {
      if (entry) await collectEntry(entry, collected);
    }
    return collected;
  }

  async function collectEntry(entry: FileSystemEntry, into: File[]) {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) =>
        (entry as FileSystemFileEntry).file(resolve, reject)
      );
      into.push(file);
      return;
    }
    if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      // readEntries returns at most ~100 entries per call until it yields an empty batch.
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
          reader.readEntries(resolve, reject)
        );
        if (batch.length === 0) break;
        for (const child of batch) await collectEntry(child, into);
      }
    }
  }

  function isDuplicate(file: File) {
    return files.some(
      (existing) =>
        existing.name === file.name &&
        existing.size === file.size &&
        existing.lastModified === file.lastModified
    );
  }

  function addFiles(newFiles: File[]) {
    const accepted: File[] = [];
    const rejected: File[] = [];
    for (const file of newFiles) {
      if (!acceptedMimeTypes.includes(file.type.split(";")[0])) {
        rejected.push(file);
      } else if (!isDuplicate(file) && !accepted.includes(file)) {
        accepted.push(file);
      }
    }
    if (!multiple) accepted.splice(1);
    if (keepSelection && accepted.length > 0) files = [...files, ...accepted];
    if (accepted.length > 0 || rejected.length > 0) onselect?.({ accepted, rejected });
  }

  function removeFile(file: File) {
    files = files.filter((existing) => existing !== file);
  }
</script>

<div
  class={cn(
    "border-border flex flex-col gap-4 rounded-xl border-2 border-dashed p-4 transition-colors",
    isDragging && "border-accent-default bg-accent-dimmer",
    disabled && "opacity-60",
    className
  )}
  data-dragging={isDragging || undefined}
  ondragenter={handleDragEnter}
  ondragover={handleDragOver}
  ondragleave={handleDragLeave}
  ondrop={handleDrop}
  role="presentation"
>
  <input
    bind:this={input}
    type="file"
    {multiple}
    {name}
    {disabled}
    accept={acceptedMimeTypes.join(",")}
    onchange={handleInputChange}
    class="sr-only"
    tabindex="-1"
    aria-hidden="true"
  />

  {#if files.length === 0}
    <button
      type="button"
      onclick={openPicker}
      {disabled}
      class="hover:bg-muted focus-visible:ring-ring/50 flex flex-col items-center gap-2 rounded-lg px-4 py-10 text-center outline-none focus-visible:ring-3 disabled:pointer-events-none"
    >
      <CloudUploadIcon class="text-muted-foreground size-8" aria-hidden="true" />
      <span class="font-medium">
        {isDragging ? m.drop_files_here() : m.upload_dropzone_prompt()}
      </span>
      {#if description}
        <span class="text-muted-foreground text-sm">{description}</span>
      {/if}
      <span class="text-accent-default text-sm underline underline-offset-4">
        {m.browse_files()}
      </span>
    </button>
  {:else}
    <ul class="flex flex-col gap-1" aria-label={m.files({ count: files.length })}>
      {#each files as file (file)}
        <li
          class="border-border bg-background flex items-center justify-between gap-2 rounded-lg border px-3 py-1.5"
        >
          <div class="flex min-w-0 items-center gap-2">
            <FileIcon class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
            <span class="truncate text-sm">{file.name}</span>
            <span class="text-muted-foreground shrink-0 text-xs">{formatBytes(file.size)}</span>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            {disabled}
            onclick={() => removeFile(file)}
            aria-label={m.remove_file({ fileName: file.name })}
          >
            <Trash2Icon aria-hidden="true" />
          </Button>
        </li>
      {/each}
    </ul>
    <Button variant="outline" size="sm" class="self-start" {disabled} onclick={openPicker}>
      <FilePlusIcon aria-hidden="true" />
      {m.add_more_files()}
    </Button>
  {/if}

  {#if groups.length > 0}
    <div
      class="border-border flex flex-col gap-2 border-t pt-3"
      role="group"
      aria-labelledby={formatsHeadingId}
    >
      <p
        id={formatsHeadingId}
        class="text-muted-foreground text-xs font-medium tracking-wide uppercase"
      >
        {m.supported_formats()}
      </p>
      <dl class="flex flex-col gap-2">
        {#each groups as group (group.kind)}
          <div class="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-3">
            <dt class="shrink-0 text-sm sm:w-40">
              {groupLabels[group.kind]()}
              {#if group.maxSizeBytes !== null}
                <span class="text-muted-foreground block text-xs">
                  {m.max_size_per_file({ size: formatBytes(group.maxSizeBytes) })}
                </span>
              {/if}
            </dt>
            <dd class="flex flex-wrap gap-1">
              {#each group.extensions as extension (extension)}
                <Badge variant="outline" class="font-mono">{extension}</Badge>
              {/each}
            </dd>
          </div>
        {/each}
      </dl>
    </div>
  {/if}
</div>
