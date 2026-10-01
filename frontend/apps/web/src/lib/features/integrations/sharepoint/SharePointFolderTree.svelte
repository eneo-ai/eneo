<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { Cloud, Earth, Info, LoaderCircle, RefreshCw, Search } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import type { components } from "@eneo/eneo-js";
  import SharePointFolderTreeNode from "./SharePointFolderTreeNode.svelte";
  import SharePointSearchResults from "./SharePointSearchResults.svelte";
  import { m } from "$lib/paraglide/messages";
  import { buildSharePointSelectionKey } from "./selectionKey";
  import {
    fetchSharePointFixtureSearch,
    fetchSharePointFixtureTree,
    type SharePointFixtureScenario
  } from "./fixtureMode";
  import {
    createSharePointTreeNode,
    isSharePointItemCovered,
    normalizeSharePointTreeQuery,
    type SharePointFilterColumn,
    type SharePointTreeItem,
    type SharePointTreeNode
  } from "./treeState";

  type ApiTreeItem = components["schemas"]["SharePointTreeItem"];

  type TreeSource = {
    userIntegrationId: string;
    spaceId: string;
    siteId?: string;
    driveId?: string;
    fixtureScenario?: SharePointFixtureScenario;
  };

  function normalizeTreeItem(item: ApiTreeItem): SharePointTreeItem | null {
    if (item.type !== "file" && item.type !== "folder" && item.type !== "site_root") {
      return null;
    }
    return {
      id: item.id,
      name: item.name,
      type: item.type,
      path: item.path,
      web_url: item.web_url ?? undefined,
      has_children: item.has_children,
      size: item.size ?? undefined,
      modified: item.modified ?? undefined,
      source_metadata: item.source_metadata ?? []
    };
  }

  interface Props {
    userIntegrationId: string;
    spaceId: string;
    siteId?: string;
    driveId?: string;
    siteName: string;
    isOneDrive: boolean;
    fixtureScenario?: SharePointFixtureScenario;
    selectedItemKeys?: string[];
    selectedPaths?: string[];
    onToggleSelect: (item: SharePointTreeItem) => void;
    /** Selects every given item that is not already covered by the selection. */
    onSelectMany?: (items: SharePointTreeItem[]) => void;
    /** Removes the given items from the selection. */
    onDeselectMany?: (items: SharePointTreeItem[]) => void;
  }

  let {
    userIntegrationId,
    spaceId,
    siteId,
    driveId,
    siteName,
    isOneDrive,
    fixtureScenario,
    selectedItemKeys = [],
    selectedPaths = [],
    onToggleSelect,
    onSelectMany,
    onDeselectMany
  }: Props = $props();

  const eneo = getEneo();
  const siteRootSelectionKey = buildSharePointSelectionKey({
    id: "",
    type: "site_root",
    path: "/"
  });

  let rootItems = $state<SharePointTreeNode[]>([]);
  let rootLoading = $state(false);
  let rootLoadError = $state(false);
  // Library columns a person can filter on without typing, from the root listing.
  let columns = $state<SharePointFilterColumn[]>([]);
  let search = $state("");
  let facets = $state<Record<string, string>>({});
  const query = $derived(normalizeSharePointTreeQuery(search));
  const activeFacets = $derived(
    Object.fromEntries(Object.entries(facets).filter(([, value]) => value !== ""))
  );
  // A search runs against the whole library, so its results replace the tree.
  const searching = $derived(query !== "" || Object.keys(activeFacets).length > 0);

  let searchResults = $state<SharePointTreeItem[]>([]);
  let searchLoading = $state(false);
  let searchError = $state(false);
  let searchTruncated = $state(false);
  let searchGeneration = 0;
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  const allMatchesSelected = $derived(
    searchResults.length > 0 &&
      searchResults.every((item) =>
        isSharePointItemCovered(item, selectedItemKeySet, selectedPaths)
      )
  );
  const canSelectMatches = $derived(
    Boolean(onSelectMany && onDeselectMany) &&
      searching &&
      !searchLoading &&
      !searchError &&
      searchResults.length > 0
  );

  function toggleAllMatches() {
    if (allMatchesSelected) {
      onDeselectMany?.(searchResults);
    } else {
      onSelectMany?.(searchResults);
    }
  }

  function clearSearch() {
    search = "";
    facets = {};
  }

  async function runSearch() {
    const generation = ++searchGeneration;
    const source = currentTreeSource();
    const text = search.trim();
    const filters = activeFacets;
    if (!text && Object.keys(filters).length === 0) {
      searchResults = [];
      searchLoading = false;
      searchError = false;
      searchTruncated = false;
      return;
    }
    searchLoading = true;
    searchError = false;
    try {
      const response = source.fixtureScenario
        ? await fetchSharePointFixtureSearch(eneo.client, source.fixtureScenario, {
            siteId: source.siteId,
            driveId: source.driveId,
            text,
            filters
          })
        : await eneo.client.fetch("/api/v1/integrations/{user_integration_id}/sharepoint/search/", {
            method: "get",
            params: {
              path: { user_integration_id: source.userIntegrationId },
              query: {
                space_id: source.spaceId,
                site_id: source.siteId,
                drive_id: source.driveId,
                q: text,
                filter: Object.entries(filters).map(([name, value]) => `${name}:${value}`)
              }
            }
          });
      if (generation !== searchGeneration) return;
      searchResults = response.items
        .map(normalizeTreeItem)
        .filter((item): item is SharePointTreeItem => item !== null);
      searchTruncated = response.truncated ?? false;
    } catch (error) {
      if (generation !== searchGeneration) return;
      searchError = true;
      searchResults = [];
      console.error("Error searching SharePoint library:", error);
    } finally {
      if (generation === searchGeneration) searchLoading = false;
    }
  }

  // Typing should not fire a Graph query per keystroke; facets apply at once.
  $effect(() => {
    void search;
    void facets;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void runSearch(), 300);
    return () => clearTimeout(searchTimer);
  });

  let treeGeneration = 0;
  let selectedItemKeySet = $derived.by(() => new Set(selectedItemKeys));
  let siteRootSelected = $derived(selectedItemKeySet.has(siteRootSelectionKey));
  let siteRootIndeterminate = $derived(!siteRootSelected && selectedPaths.length > 0);

  function currentTreeSource(): TreeSource {
    return { userIntegrationId, spaceId, siteId, driveId, fixtureScenario };
  }

  async function fetchTree(
    source: TreeSource,
    folderId?: string,
    folderPath?: string
  ): Promise<{ items: SharePointTreeNode[]; columns: SharePointFilterColumn[] }> {
    const queryParams: {
      space_id: string;
      site_id?: string;
      drive_id?: string;
      folder_id?: string;
      folder_path?: string;
    } = { space_id: source.spaceId };

    if (source.siteId) queryParams.site_id = source.siteId;
    if (source.driveId) queryParams.drive_id = source.driveId;
    if (folderId) queryParams.folder_id = folderId;
    if (folderPath) queryParams.folder_path = folderPath;

    const response = source.fixtureScenario
      ? await fetchSharePointFixtureTree(eneo.client, source.fixtureScenario, {
          siteId: source.siteId,
          driveId: source.driveId,
          folderId,
          folderPath
        })
      : await eneo.client.fetch("/api/v1/integrations/{user_integration_id}/sharepoint/tree/", {
          method: "get",
          params: {
            path: { user_integration_id: source.userIntegrationId },
            query: queryParams
          }
        });

    return {
      items: response.items
        .map(normalizeTreeItem)
        .filter((item): item is SharePointTreeItem => item !== null)
        .map(createSharePointTreeNode),
      columns: response.columns ?? []
    };
  }

  async function fetchTreeItems(
    source: TreeSource,
    folderId?: string,
    folderPath?: string
  ): Promise<SharePointTreeNode[]> {
    return (await fetchTree(source, folderId, folderPath)).items;
  }

  async function loadRoot(source: TreeSource) {
    const generation = ++treeGeneration;
    rootItems = [];
    rootLoading = true;
    rootLoadError = false;

    try {
      const tree = await fetchTree(source);
      if (generation !== treeGeneration) return;
      rootItems = tree.items;
      columns = tree.columns;
    } catch (error) {
      if (generation !== treeGeneration) return;
      rootLoadError = true;
      console.error("Error loading SharePoint tree:", error);
    } finally {
      if (generation === treeGeneration) rootLoading = false;
    }
  }

  async function loadNodeChildren(node: SharePointTreeNode) {
    const generation = treeGeneration;
    node.loading = true;
    node.loadError = false;

    try {
      const children = await fetchTreeItems(currentTreeSource(), node.id, node.path);
      if (generation !== treeGeneration) return;
      node.children = children;
    } catch (error) {
      if (generation !== treeGeneration) return;
      node.children = null;
      node.loadError = true;
      console.error("Error loading SharePoint folder:", error);
    } finally {
      if (generation === treeGeneration) node.loading = false;
    }
  }

  function toggleNodeExpanded(node: SharePointTreeNode) {
    node.expanded = !node.expanded;
    if (node.expanded && node.children === null && !node.loading) void loadNodeChildren(node);
  }

  function retryNodeLoad(node: SharePointTreeNode) {
    node.expanded = true;
    void loadNodeChildren(node);
  }

  function handleImportEntireSite() {
    onToggleSelect({
      id: "",
      name: siteName,
      type: "site_root",
      path: "/",
      has_children: true
    });
  }

  $effect(() => {
    const source = currentTreeSource();
    if (source.siteId || source.driveId) void loadRoot(source);
    else {
      treeGeneration += 1;
      rootItems = [];
      rootLoading = false;
      rootLoadError = false;
    }
  });
</script>

<div class="flex min-h-0 flex-1 flex-col gap-3">
  <p class="text-muted-foreground flex items-start gap-2 px-1 text-sm">
    <Info class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
    {m.sharepoint_tree_selection_description()}
  </p>

  <div class="flex flex-col gap-2">
    <div class="flex flex-wrap items-center gap-2">
      <InputGroup.Root class="bg-background min-w-56 flex-1">
        <InputGroup.Addon>
          <Search class="size-4 shrink-0 opacity-60" aria-hidden="true" />
        </InputGroup.Addon>
        <InputGroup.Input
          type="search"
          bind:value={search}
          placeholder={m.sharepoint_search_content({ name: siteName })}
          aria-label={m.sharepoint_search_content({ name: siteName })}
          aria-describedby="sharepoint-search-help"
          autocomplete="off"
        />
      </InputGroup.Root>
      <!-- Library columns with fixed values: a person picks instead of typing. -->
      {#each columns as column (column.name)}
        <Select.Root
          type="single"
          value={facets[column.name] ?? ""}
          onValueChange={(value) => (facets = { ...facets, [column.name]: value })}
        >
          <Select.Trigger
            aria-label={m.sharepoint_filter_label({ column: column.label })}
            class="h-10 max-w-64 min-w-40"
          >
            <span class="text-muted-foreground">{column.label}:</span>
            {#if column.kind === "boolean"}
              {facets[column.name] === "true"
                ? m.yes()
                : facets[column.name] === "false"
                  ? m.no()
                  : m.sharepoint_filter_any()}
            {:else}
              {facets[column.name] || m.sharepoint_filter_any()}
            {/if}
          </Select.Trigger>
          <Select.Content>
            <Select.Item value="" label={m.sharepoint_filter_any()}>
              {m.sharepoint_filter_any()}
            </Select.Item>
            {#if column.kind === "boolean"}
              <Select.Item value="true" label={m.yes()}>{m.yes()}</Select.Item>
              <Select.Item value="false" label={m.no()}>{m.no()}</Select.Item>
            {:else}
              {#each column.choices as choice (choice)}
                <Select.Item value={choice} label={choice}>{choice}</Select.Item>
              {/each}
            {/if}
          </Select.Content>
        </Select.Root>
      {/each}
    </div>
    <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-1">
      <p id="sharepoint-search-help" class="text-muted-foreground text-xs" aria-live="polite">
        {#if searching && !searchLoading && !searchError}
          {searchResults.length === 1
            ? m.sharepoint_search_results_one({ count: String(searchResults.length) })
            : m.sharepoint_search_results_other({ count: String(searchResults.length) })}
        {:else}
          {m.sharepoint_search_help()}
        {/if}
      </p>
      <div class="flex flex-wrap items-center gap-2">
        {#if searching}
          <Button variant="ghost" size="sm" onclick={clearSearch}>
            {m.sharepoint_search_clear()}
          </Button>
        {/if}
        {#if canSelectMatches}
          <!-- One press instead of a checkbox per hit. -->
          <Button
            variant="outline"
            size="sm"
            disabled={siteRootSelected}
            title={siteRootSelected ? m.sharepoint_selected_by_parent() : undefined}
            onclick={toggleAllMatches}
          >
            {allMatchesSelected
              ? m.sharepoint_deselect_all_matches()
              : m.sharepoint_select_all_matches({ count: String(searchResults.length) })}
          </Button>
        {/if}
      </div>
    </div>
  </div>

  {#if searching}
    <SharePointSearchResults
      items={searchResults}
      {query}
      loading={searchLoading}
      error={searchError}
      truncated={searchTruncated}
      {selectedItemKeySet}
      {selectedPaths}
      {onToggleSelect}
      onRetry={() => void runSearch()}
    />
  {:else}
    <div
      class="border-border bg-card min-h-56 flex-1 overflow-x-hidden overflow-y-auto rounded-lg border"
      aria-busy={rootLoading}
    >
      {#if rootLoading}
        <div
          class="text-muted-foreground flex items-center justify-center gap-2 px-4 py-10"
          role="status"
        >
          <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
          {m.sharepoint_loading_content()}
        </div>
      {:else if rootLoadError}
        <div class="flex flex-col items-center gap-3 px-4 py-10 text-center" role="alert">
          <p class="text-destructive text-sm">{m.sharepoint_tree_load_error()}</p>
          <Button variant="outline" size="sm" onclick={() => loadRoot(currentTreeSource())}>
            <RefreshCw aria-hidden="true" />
            {m.retry()}
          </Button>
        </div>
      {:else if rootItems.length === 0}
        <div class="text-muted-foreground px-4 py-10 text-center text-sm">
          {m.no_items()}
        </div>
      {:else}
        <div
          class="border-border flex min-h-11 w-full items-center gap-2 border-b px-3 text-left transition-colors
          {siteRootSelected ? 'bg-accent-dimmer/60' : 'hover:bg-muted/50'}"
        >
          <Checkbox
            id="sharepoint-entire-site"
            aria-label={isOneDrive ? m.import_entire_onedrive() : m.import_entire_site()}
            checked={siteRootSelected}
            indeterminate={siteRootIndeterminate}
            onCheckedChange={handleImportEntireSite}
          />
          <label
            for="sharepoint-entire-site"
            class="flex h-10 min-w-0 flex-1 cursor-pointer items-center gap-2 px-2 font-medium"
          >
            {#if isOneDrive}
              <Cloud class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
            {:else}
              <Earth class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
            {/if}
            {isOneDrive ? m.import_entire_onedrive() : m.import_entire_site()}
          </label>
        </div>

        <ul role="tree" aria-label={siteName} class="flex flex-col">
          {#each rootItems as item (buildSharePointSelectionKey(item))}
            <SharePointFolderTreeNode
              node={item}
              {selectedItemKeySet}
              {selectedPaths}
              ancestorSelected={siteRootSelected}
              {onToggleSelect}
              onToggleExpanded={toggleNodeExpanded}
              onRetryLoad={retryNodeLoad}
            />
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
</div>
