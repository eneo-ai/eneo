<script lang="ts">
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getIntric } from "$lib/core/Intric";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconWeb } from "@intric/icons/web";
  import { IconUploadCloud } from "@intric/icons/upload-cloud";
  import SharePointFolderTreeNode from "./SharePointFolderTreeNode.svelte";
  import { m } from "$lib/paraglide/messages";
  import { buildSharePointSelectionKey } from "./selectionKey";

  type TreeItem = {
    id: string;
    name: string;
    type: "file" | "folder" | "site_root";
    path: string;
    web_url?: string;
    has_children: boolean;
    size?: number;
    modified?: string;
  };

  interface Props {
    userIntegrationId: string;
    spaceId: string;
    siteId?: string;
    driveId?: string;
    siteName: string;
    isOneDrive: boolean;
    selectedItemKeys?: string[];
    onToggleSelect: (item: TreeItem) => void;
  }

  let {
    userIntegrationId,
    spaceId,
    siteId,
    driveId,
    siteName,
    isOneDrive,
    selectedItemKeys,
    onToggleSelect
  }: Props = $props();

  const intric = getIntric();

  let currentItems = $state<TreeItem[]>([]);
  let navigationStack = $state<Array<{ folderId: string | null; path: string; name: string }>>(
    [{ folderId: null, path: "/", name: siteName }]
  );
  let selectedItemKeySet = $derived.by(() => new Set(selectedItemKeys ?? []));
  const siteRootSelectionKey = buildSharePointSelectionKey({
    id: "",
    type: "site_root",
    path: "/"
  });

  function getItemSelectionKey(item: TreeItem): string {
    return buildSharePointSelectionKey(item);
  }

  // Guard against stale responses when navigating quickly
  let requestId = 0;

  const loadFolders = createAsyncState(async (folderId: string | null = null, folderPath: string = "") => {
    const thisRequest = ++requestId;
    try {
      const queryParams: Record<string, string> = {
        space_id: spaceId
      };

      if (siteId) {
        queryParams.site_id = siteId;
      }
      if (driveId) {
        queryParams.drive_id = driveId;
      }

      if (folderId !== null) {
        queryParams.folder_id = folderId;
      }

      if (folderPath) {
        queryParams.folder_path = folderPath;
      }

      const response = await intric.client.fetch(
        `/api/v1/integrations/${userIntegrationId}/sharepoint/tree/`,
        {
          method: "get",
          params: {
            query: queryParams
          }
        }
      );

      // Ignore stale responses from earlier navigations
      if (thisRequest !== requestId) return;

      currentItems = response.items || [];
    } catch (error) {
      if (thisRequest !== requestId) return;
      console.error("Error loading folder tree:", error);
    }
  });

  const handleNodeSelect = (item: TreeItem) => {
    onToggleSelect(item);
  };

  const handleNodeNavigate = (item: TreeItem) => {
    if (item.type === "folder") {
      navigationStack.push({ folderId: item.id, path: item.path, name: item.name });
      loadFolders(item.id, item.path);
    }
  };

  const navigateTo = (index: number) => {
    if (index < navigationStack.length - 1) {
      navigationStack = navigationStack.slice(0, index + 1);
      const target = navigationStack[index];
      const targetFolderPath = target.path === "/" ? "" : target.path;
      loadFolders(target.folderId, targetFolderPath);
    }
  };

  const handleImportEntireSite = () => {
    onToggleSelect({
      id: "",
      name: siteName,
      type: "site_root",
      path: "/",
      has_children: true
    });
  };

  const handleImportEntireSiteCheckboxClick = (event: MouseEvent) => {
    event.stopPropagation();
    handleImportEntireSite();
  };

  $effect(() => {
    if (siteId || driveId) {
      loadFolders();
    }
  });
</script>

<div class="flex flex-col gap-2 p-4">
  <!-- Breadcrumb -->
  {#if navigationStack.length > 1}
    <nav class="flex items-center gap-0.5 text-sm flex-wrap min-h-[28px]">
      {#each navigationStack as segment, i}
        {#if i > 0}
          <IconChevronRight class="w-3 h-3 text-secondary flex-shrink-0" />
        {/if}
        {#if i < navigationStack.length - 1}
          <button
            type="button"
            class="text-secondary hover:text-primary hover:underline px-1 py-0.5 rounded truncate max-w-[150px]"
            onclick={() => navigateTo(i)}
          >
            {segment.name}
          </button>
        {:else}
          <span class="text-primary font-medium px-1 py-0.5 truncate max-w-[200px]">{segment.name}</span>
        {/if}
      {/each}
    </nav>
  {/if}

  <div class="border border-default rounded-md overflow-y-auto max-h-96 bg-primary">
    {#if loadFolders.isLoading && currentItems.length === 0}
      <div class="flex items-center gap-2 px-4 py-8 text-secondary">
        <IconLoadingSpinner class="animate-spin w-4 h-4" />
        {m.loading_available_sites()}
      </div>
    {:else if currentItems.length === 0}
      <div class="px-4 py-4 text-secondary text-sm">
        {m.no_items()}
      </div>
    {:else}
      <div class="flex flex-col">
        <!-- Import entire site row -->
        {#if navigationStack.length <= 1}
          <div
            class="flex items-center gap-2 px-3 py-1.5 cursor-pointer text-left w-full border-b border-default transition-colors
              {selectedItemKeySet.has(siteRootSelectionKey) ? 'bg-accent-dimmer border-accent' : 'hover:bg-hover-default'}"
          >
            <div class="w-3.5"></div>
            <input
              type="checkbox"
              class="h-4 w-4 accent-accent-default flex-shrink-0"
              checked={selectedItemKeySet.has(siteRootSelectionKey)}
              onclick={handleImportEntireSiteCheckboxClick}
            />
            {#if isOneDrive}
              <IconUploadCloud class="w-4 h-4 flex-shrink-0 text-secondary" />
            {:else}
              <IconWeb class="w-4 h-4 flex-shrink-0 text-secondary" />
            {/if}
            <button
              type="button"
              class="text-sm font-medium text-left w-full"
              onclick={handleImportEntireSite}
            >
              {isOneDrive ? m.import_entire_onedrive() : m.import_entire_site()}
            </button>
          </div>
        {/if}

        {#each currentItems as item (getItemSelectionKey(item))}
          <SharePointFolderTreeNode
            node={item}
            isSelected={selectedItemKeySet.has(getItemSelectionKey(item))}
            onToggleSelect={handleNodeSelect}
            onNavigate={handleNodeNavigate}
          />
        {/each}
      </div>
    {/if}
  </div>
</div>
