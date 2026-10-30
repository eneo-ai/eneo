<script lang="ts">
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import File from "@lucide/svelte/icons/file";
  import FileHeadphone from "@lucide/svelte/icons/file-headphone";
  import FileImage from "@lucide/svelte/icons/file-image";
  import FileText from "@lucide/svelte/icons/file-text";
  import Folder from "@lucide/svelte/icons/folder";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import { m } from "$lib/paraglide/messages";
  import { formatFileSize, formatModifiedDate } from "./format";
  import SourceMetadataList from "$lib/features/knowledge/components/SourceMetadataList.svelte";
  import { hasSourceMetadata } from "$lib/features/knowledge/sourceMetadata";
  import { buildSharePointSelectionKey } from "./selectionKey";
  import {
    hasSelectedSharePointDescendant,
    type SharePointTreeItem,
    type SharePointTreeNode
  } from "./treeState";

  interface Props {
    node: SharePointTreeNode;
    selectedItemKeySet: Set<string>;
    selectedPaths: string[];
    ancestorSelected?: boolean;
    /** The one tree item in the tab order (roving tabindex); null leaves every item out. */
    activeKey?: string | null;
    onToggleSelect: (node: SharePointTreeItem) => void;
    onToggleExpanded: (node: SharePointTreeNode) => void;
    onRetryLoad: (node: SharePointTreeNode) => void;
  }

  let {
    node,
    selectedItemKeySet,
    selectedPaths,
    ancestorSelected = false,
    activeKey = null,
    onToggleSelect,
    onToggleExpanded,
    onRetryLoad
  }: Props = $props();

  const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "svg", "bmp", "webp", "ico", "tiff"];
  const AUDIO_EXTENSIONS = ["mp3", "wav", "ogg", "flac", "aac", "wma", "m4a"];
  const TEXT_EXTENSIONS = [
    "doc",
    "docx",
    "pdf",
    "txt",
    "rtf",
    "odt",
    "xls",
    "xlsx",
    "csv",
    "ppt",
    "pptx",
    "md",
    "html",
    "xml",
    "json"
  ];

  function getFileExtension(name: string): string {
    const parts = name.split(".");
    return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
  }
</script>

{#snippet renderNode(currentNode: SharePointTreeNode, parentSelected: boolean)}
  {@const selectionKey = buildSharePointSelectionKey(currentNode)}
  {@const directlySelected = selectedItemKeySet.has(selectionKey)}
  {@const selected = parentSelected || directlySelected}
  {@const indeterminate =
    !selected &&
    currentNode.type === "folder" &&
    hasSelectedSharePointDescendant(selectedPaths, currentNode.path)}
  {@const checkboxId = `sharepoint-item-${currentNode.id}`}
  {@const coveredDescriptionId = `sharepoint-item-${currentNode.id}-covered`}
  {@const expanded = currentNode.expanded}
  <!-- The treeitem is the accessible checkbox (aria-checked, Space); the inner
       control is a pointer target only, so it is hidden from assistive tech
       rather than announced a second time. ARIA 1.2 dropped aria-selected as a
       required treeitem attribute; Svelte's check still follows 1.1. -->
  <!-- svelte-ignore a11y_role_has_required_aria_props -->
  <li
    role="treeitem"
    aria-label={currentNode.name}
    aria-checked={selected ? "true" : indeterminate ? "mixed" : "false"}
    aria-describedby={parentSelected ? coveredDescriptionId : undefined}
    aria-expanded={currentNode.type === "folder" && currentNode.has_children ? expanded : undefined}
    tabindex={selectionKey === activeKey ? 0 : -1}
    data-tree-key={selectionKey}
    class="focus-visible:ring-stronger outline-none focus-visible:ring-2 focus-visible:ring-inset"
  >
    {#if parentSelected}
      <span id={coveredDescriptionId} class="sr-only">{m.sharepoint_selected_by_parent()}</span>
    {/if}
    <div
      class="border-border flex min-h-11 w-full min-w-0 items-center gap-2 border-b px-3 text-left transition-colors
        {selected ? 'bg-accent-dimmer/60' : 'hover:bg-muted/50'}"
    >
      <Checkbox
        id={checkboxId}
        aria-hidden="true"
        checked={selected}
        {indeterminate}
        disabled={parentSelected}
        tabindex={-1}
        onCheckedChange={() => onToggleSelect(currentNode)}
      />

      {#if currentNode.type === "folder" && currentNode.has_children}
        <Button
          variant="ghost"
          class="h-10 min-w-0 flex-1 justify-start px-2"
          aria-label={expanded
            ? m.sharepoint_collapse_folder_named({ name: currentNode.name })
            : m.sharepoint_expand_folder_named({ name: currentNode.name })}
          tabindex={-1}
          onclick={() => onToggleExpanded(currentNode)}
        >
          <ChevronRight
            class="size-4 shrink-0 transition-transform {expanded ? 'rotate-90' : ''}"
            aria-hidden="true"
          />
          {#if expanded}
            <FolderOpen class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
          {:else}
            <Folder class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
          {/if}
          <span class="min-w-0 flex-1 truncate text-left" title={currentNode.name}>
            {currentNode.name}
          </span>
          {#if currentNode.modified}
            <span class="text-muted-foreground hidden shrink-0 text-xs tabular-nums lg:inline">
              {formatModifiedDate(currentNode.modified)}
            </span>
          {/if}
        </Button>
      {:else if currentNode.type === "folder"}
        <label
          for={checkboxId}
          class="flex h-10 min-w-0 flex-1 cursor-pointer items-center gap-2 px-2"
        >
          <span class="size-4 shrink-0" aria-hidden="true"></span>
          <Folder class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
          <span class="min-w-0 flex-1 truncate text-left" title={currentNode.name}>
            {currentNode.name}
          </span>
          <span class="text-muted-foreground hidden shrink-0 text-xs md:inline">
            {m.sharepoint_empty_folder()}
          </span>
        </label>
      {:else}
        {@const ext = getFileExtension(currentNode.name)}
        <label
          for={checkboxId}
          class="flex min-h-10 min-w-0 flex-1 cursor-pointer items-center gap-2 px-2 py-1"
        >
          <span class="size-4 shrink-0" aria-hidden="true"></span>
          {#if IMAGE_EXTENSIONS.includes(ext)}
            <FileImage class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
          {:else if AUDIO_EXTENSIONS.includes(ext)}
            <FileHeadphone class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
          {:else if TEXT_EXTENSIONS.includes(ext)}
            <FileText class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
          {:else}
            <File class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
          {/if}
          <span class="flex min-w-0 flex-1 flex-col text-left">
            <span class="truncate" title={currentNode.name}>{currentNode.name}</span>
            {#if hasSourceMetadata(currentNode)}
              <!-- The library columns that follow the file on import: lets a
                   person see what becomes searchable before choosing. -->
              <SourceMetadataList
                entries={currentNode.source_metadata}
                variant="inline"
                class="text-muted-foreground text-xs"
              />
            {/if}
          </span>
          {#if currentNode.size != null}
            <span class="text-muted-foreground hidden shrink-0 text-xs tabular-nums md:inline">
              {formatFileSize(currentNode.size)}
            </span>
          {/if}
          {#if currentNode.modified}
            <span class="text-muted-foreground hidden shrink-0 text-xs tabular-nums lg:inline">
              {formatModifiedDate(currentNode.modified)}
            </span>
          {/if}
        </label>
      {/if}
    </div>

    {#if currentNode.type === "folder" && expanded}
      <ul role="group" class="border-border ml-4 border-l sm:ml-5">
        {#if currentNode.loading}
          <li role="none">
            <div
              class="text-muted-foreground flex min-h-11 items-center gap-2 px-4 text-sm"
              role="status"
            >
              <LoaderCircle class="size-4 motion-safe:animate-spin" aria-hidden="true" />
              {m.sharepoint_loading_content()}
            </div>
          </li>
        {:else if currentNode.loadError}
          <li role="none">
            <div class="flex min-h-11 flex-wrap items-center gap-2 px-4 py-2" role="alert">
              <span class="text-destructive min-w-0 flex-1 text-sm">
                {m.sharepoint_tree_load_error()}
              </span>
              <Button variant="outline" size="sm" onclick={() => onRetryLoad(currentNode)}>
                <RefreshCw aria-hidden="true" />
                {m.retry()}
              </Button>
            </div>
          </li>
        {:else if currentNode.children?.length === 0}
          <li role="none">
            <div class="text-muted-foreground min-h-11 px-4 py-3 text-sm">
              {m.no_items()}
            </div>
          </li>
        {:else}
          {#each currentNode.children ?? [] as child (buildSharePointSelectionKey(child))}
            {@render renderNode(child, selected)}
          {/each}
        {/if}
        {#if currentNode.childrenTruncated && !currentNode.loading && !currentNode.loadError}
          <li role="none">
            <p class="text-muted-foreground px-4 py-2 text-xs" role="status">
              {m.sharepoint_tree_truncated()}
            </p>
          </li>
        {/if}
      </ul>
    {/if}
  </li>
{/snippet}

{@render renderNode(node, ancestorSelected)}
