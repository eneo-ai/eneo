<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { Cloud, Earth, Info, LoaderCircle, RefreshCw, Search } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import type { components } from "@eneo/eneo-js";
  import SharePointFolderTreeNode from "./SharePointFolderTreeNode.svelte";
  import { m } from "$lib/paraglide/messages";
  import { buildSharePointSelectionKey } from "./selectionKey";
  import { fetchSharePointFixtureTree, type SharePointFixtureScenario } from "./fixtureMode";
  import {
    countSharePointTreeMatches,
    createSharePointTreeNode,
    normalizeSharePointTreeQuery,
    sharePointTreeNodeVisible,
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
    onToggleSelect
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
  let search = $state("");
  const query = $derived(normalizeSharePointTreeQuery(search));
  const visibleRootItems = $derived(
    rootItems.filter((item) => sharePointTreeNodeVisible(item, query))
  );
  const matchCount = $derived(countSharePointTreeMatches(rootItems, query));
  let treeGeneration = 0;
  let selectedItemKeySet = $derived.by(() => new Set(selectedItemKeys));
  let siteRootSelected = $derived(selectedItemKeySet.has(siteRootSelectionKey));
  let siteRootIndeterminate = $derived(!siteRootSelected && selectedPaths.length > 0);

  function currentTreeSource(): TreeSource {
    return { userIntegrationId, spaceId, siteId, driveId, fixtureScenario };
  }

  async function fetchTreeItems(
    source: TreeSource,
    folderId?: string,
    folderPath?: string
  ): Promise<SharePointTreeNode[]> {
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

    return response.items
      .map(normalizeTreeItem)
      .filter((item): item is SharePointTreeItem => item !== null)
      .map(createSharePointTreeNode);
  }

  async function loadRoot(source: TreeSource) {
    const generation = ++treeGeneration;
    rootItems = [];
    rootLoading = true;
    rootLoadError = false;

    try {
      const items = await fetchTreeItems(source);
      if (generation !== treeGeneration) return;
      rootItems = items;
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

  <div class="flex flex-col gap-1">
    <InputGroup.Root class="bg-background">
      <InputGroup.Addon>
        <Search class="size-4 shrink-0 opacity-60" aria-hidden="true" />
      </InputGroup.Addon>
      <InputGroup.Input
        type="search"
        bind:value={search}
        placeholder={m.sharepoint_search_content({ name: siteName })}
        aria-label={m.sharepoint_search_content({ name: siteName })}
        aria-describedby="sharepoint-search-scope"
        autocomplete="off"
      />
    </InputGroup.Root>
    <!-- Names and document properties of what has been opened so far; folders
         that were never expanded are not fetched just to search them. -->
    <p id="sharepoint-search-scope" class="text-muted-foreground px-1 text-xs" aria-live="polite">
      {#if query}
        {matchCount === 1
          ? m.sharepoint_search_matches_one({ count: matchCount })
          : m.sharepoint_search_matches_other({ count: matchCount })}
        · {m.sharepoint_search_scope_hint()}
      {:else}
        {m.sharepoint_search_scope_hint()}
      {/if}
    </p>
  </div>

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

      {#if query && visibleRootItems.length === 0}
        <div class="text-muted-foreground px-4 py-10 text-center text-sm" role="status">
          {m.sharepoint_search_no_matches()}
        </div>
      {:else}
        <ul role="tree" aria-label={siteName} class="flex flex-col">
          {#each visibleRootItems as item (buildSharePointSelectionKey(item))}
            <SharePointFolderTreeNode
              node={item}
              {query}
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
    {/if}
  </div>
</div>
