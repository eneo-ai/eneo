<script lang="ts">
  import { File, FileText, LoaderCircle, RefreshCw } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import HighlightedText from "$lib/components/HighlightedText.svelte";
  import SourceMetadataList from "$lib/features/knowledge/components/SourceMetadataList.svelte";
  import { hasSourceMetadata } from "$lib/features/knowledge/sourceMetadata";
  import { m } from "$lib/paraglide/messages";
  import { formatFileSize, formatModifiedDate } from "./format";
  import { buildSharePointSelectionKey } from "./selectionKey";
  import { isSharePointItemCovered, type SharePointTreeItem } from "./treeState";

  /**
   * Files from a whole-library search, as a flat list a person can tick. Each
   * row shows where the file lives and which part of it the search hit.
   */
  let {
    items,
    query,
    loading,
    error,
    truncated,
    selectedItemKeySet,
    selectedPaths,
    onToggleSelect,
    onRetry
  }: {
    items: SharePointTreeItem[];
    /** Normalised free text, for highlighting. */
    query: string;
    loading: boolean;
    error: boolean;
    truncated: boolean;
    selectedItemKeySet: Set<string>;
    selectedPaths: string[];
    onToggleSelect: (item: SharePointTreeItem) => void;
    onRetry: () => void;
  } = $props();

  const TEXT_LIKE = /\.(docx?|pdf|txt|md|xlsx?|pptx?|csv)$/i;

  function folderOf(path: string): string {
    const at = path.lastIndexOf("/");
    return at > 0 ? path.slice(0, at) : "/";
  }
</script>

<div
  class="border-border bg-card min-h-56 flex-1 overflow-x-hidden overflow-y-auto rounded-lg border"
  aria-busy={loading}
>
  {#if loading}
    <div
      class="text-muted-foreground flex items-center justify-center gap-2 px-4 py-10"
      role="status"
    >
      <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
      {m.sharepoint_searching()}
    </div>
  {:else if error}
    <div class="flex flex-col items-center gap-3 px-4 py-10 text-center" role="alert">
      <p class="text-destructive text-sm">{m.sharepoint_search_error()}</p>
      <Button variant="outline" size="sm" onclick={onRetry}>
        <RefreshCw aria-hidden="true" />
        {m.retry()}
      </Button>
    </div>
  {:else if items.length === 0}
    <div class="text-muted-foreground px-4 py-10 text-center text-sm" role="status">
      {m.sharepoint_search_no_results()}
    </div>
  {:else}
    <ul aria-label={m.sharepoint_search_results_label()} class="flex flex-col">
      {#each items as item (buildSharePointSelectionKey(item))}
        {@const directlySelected = selectedItemKeySet.has(buildSharePointSelectionKey(item))}
        {@const covered = isSharePointItemCovered(item, selectedItemKeySet, selectedPaths)}
        {@const checkboxId = `sharepoint-result-${item.id}`}
        <li
          class="border-border flex w-full min-w-0 items-start gap-2 border-b px-3 py-1 transition-colors
            {covered ? 'bg-accent-dimmer/60' : 'hover:bg-muted/50'}"
        >
          <Checkbox
            id={checkboxId}
            class="mt-2.5"
            aria-label={m.sharepoint_select_item({ name: item.name })}
            checked={covered}
            disabled={covered && !directlySelected}
            title={covered && !directlySelected ? m.sharepoint_selected_by_parent() : undefined}
            onCheckedChange={() => onToggleSelect(item)}
          />
          <label
            for={checkboxId}
            class="flex min-h-10 min-w-0 flex-1 cursor-pointer items-center gap-2 px-2 py-1"
          >
            {#if TEXT_LIKE.test(item.name)}
              <FileText class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
            {:else}
              <File class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
            {/if}
            <span class="flex min-w-0 flex-1 flex-col text-left">
              <span class="truncate" title={item.name}>
                <HighlightedText text={item.name} {query} />
              </span>
              <span class="text-muted-foreground truncate text-xs" title={folderOf(item.path)}>
                {folderOf(item.path)}
              </span>
              {#if hasSourceMetadata(item)}
                <SourceMetadataList
                  entries={item.source_metadata}
                  variant="inline"
                  highlight={query}
                  class="text-muted-foreground text-xs"
                />
              {/if}
            </span>
            {#if item.size != null}
              <span class="text-muted-foreground hidden shrink-0 text-xs tabular-nums md:inline">
                {formatFileSize(item.size)}
              </span>
            {/if}
            {#if item.modified}
              <span class="text-muted-foreground hidden shrink-0 text-xs tabular-nums lg:inline">
                {formatModifiedDate(item.modified)}
              </span>
            {/if}
          </label>
        </li>
      {/each}
    </ul>
    {#if truncated}
      <p class="text-muted-foreground px-4 py-3 text-xs" role="status">
        {m.sharepoint_search_truncated({ count: String(items.length) })}
      </p>
    {/if}
  {/if}
</div>
