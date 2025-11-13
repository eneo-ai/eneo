<script lang="ts">
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getIntric } from "$lib/core/Intric";
  import { IconChevronUp } from "@intric/icons/chevron-up";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import SharePointFolderTreeNode from "./SharePointFolderTreeNode.svelte";
  import { m } from "$lib/paraglide/messages";

  type TreeItem = {
    id: string;
    name: string;
    type: "file" | "folder";
    path: string;
    has_children: boolean;
    size?: number;
    modified?: string;
  };

  interface Props {
    userIntegrationId: string;
    spaceId: string;
    siteId: string;
    onSelect: (item: TreeItem) => void;
  }

  let { userIntegrationId, spaceId, siteId, onSelect }: Props = $props();

  const intric = getIntric();

  let currentItems = $state<TreeItem[]>([]);
  let currentPath = $state<string>("/");
  let currentFolderId = $state<string | null>(null);
  let driveId = $state<string>("");
  let expandedNodes = $state<Set<string>>(new Set());
  let loadingNodes = $state<Set<string>>(new Set());
  let navigationStack = $state<Array<{ folderId: string | null; path: string }>>(
    [{ folderId: null, path: "/" }]
  );

  const loadFolders = createAsyncState(async (folderId: string | null = null, folderPath: string = "") => {
    try {
      // Build query params, only including defined values
      const queryParams: Record<string, string> = {
        space_id: spaceId,
        site_id: siteId
      };

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

      currentItems = response.items || [];
      currentPath = response.current_path || "/";
      currentFolderId = folderId;
      driveId = response.drive_id;

      if (folderId) {
        loadingNodes.delete(folderId);
      }
    } catch (error) {
      console.error("Error loading folder tree:", error);
      if (folderId) {
        loadingNodes.delete(folderId);
      }
    }
  });

  const handleNodeToggle = async (nodeId: string) => {
    if (expandedNodes.has(nodeId)) {
      expandedNodes.delete(nodeId);
    } else {
      expandedNodes.add(nodeId);
      loadingNodes.add(nodeId);

      const node = currentItems.find((item) => item.id === nodeId);
      if (node) {
        await loadFolders(nodeId, node.path);
      }
    }
  };

  const handleNodeSelect = (item: TreeItem) => {
    onSelect(item);
  };

  const handleNodeNavigate = (item: TreeItem) => {
    if (item.type === "folder") {
      navigationStack.push({ folderId: item.id, path: item.path });
      currentFolderId = item.id;
      expandedNodes.clear();
      loadFolders(item.id, item.path);
    }
  };

  const navigateBack = () => {
    if (navigationStack.length > 1) {
      navigationStack.pop();
      const previous = navigationStack[navigationStack.length - 1];
      currentFolderId = previous.folderId;
      expandedNodes.clear();
      loadFolders(previous.folderId, previous.path);
    }
  };

  $effect(() => {
    if (siteId) {
      loadFolders();
    }
  });
</script>

<div class="flex flex-col gap-3 p-4">
  <div class="flex items-center justify-between">
    <div class="flex items-center gap-2">
      {#if navigationStack.length > 1}
        <button
          onclick={navigateBack}
          class="flex items-center gap-1 px-2 py-1 hover:bg-hover-default rounded-md text-sm"
        >
          <IconChevronUp class="w-4 h-4" />
          {m.back()}
        </button>
      {/if}
      <span class="text-sm text-secondary truncate">{currentPath}</span>
    </div>
  </div>

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
        {#each currentItems as item (item.id)}
          <SharePointFolderTreeNode
            node={item}
            isExpanded={expandedNodes.has(item.id)}
            isLoading={loadingNodes.has(item.id)}
            onToggle={handleNodeToggle}
            onSelect={handleNodeSelect}
            onNavigate={handleNodeNavigate}
          />
        {/each}
      </div>
    {/if}
  </div>
</div>
