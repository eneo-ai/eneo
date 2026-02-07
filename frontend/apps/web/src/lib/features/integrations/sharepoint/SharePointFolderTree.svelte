<script lang="ts">
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getIntric } from "$lib/core/Intric";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconWeb } from "@intric/icons/web";
  import { IconUploadCloud } from "@intric/icons/upload-cloud";
  import SharePointFolderTreeNode from "./SharePointFolderTreeNode.svelte";
  import { m } from "$lib/paraglide/messages";

  type TreeItem = {
    id: string;
    name: string;
    type: "file" | "folder" | "site_root";
    path: string;
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
    selectedItemId?: string;
    onSelect: (item: TreeItem) => void;
  }

  let {
    userIntegrationId,
    spaceId,
    siteId,
    driveId,
    siteName,
    isOneDrive,
    selectedItemId,
    onSelect
  }: Props = $props();

  const intric = getIntric();

  let currentItems = $state<TreeItem[]>([]);
  let currentPath = $state<string>("/");
  let currentFolderId = $state<string | null>(null);
  let currentDriveId = $state<string>("");
  let navigationStack = $state<Array<{ folderId: string | null; path: string; name: string }>>(
    [{ folderId: null, path: "/", name: siteName }]
  );

  const loadFolders = createAsyncState(async (folderId: string | null = null, folderPath: string = "") => {
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

      currentItems = response.items || [];
      currentPath = response.current_path || "/";
      currentFolderId = folderId;
      currentDriveId = response.drive_id;
    } catch (error) {
      console.error("Error loading folder tree:", error);
    }
  });

  const handleNodeSelect = (item: TreeItem) => {
    onSelect(item);
  };

  const handleNodeNavigate = (item: TreeItem) => {
    if (item.type === "folder") {
      navigationStack.push({ folderId: item.id, path: item.path, name: item.name });
      currentFolderId = item.id;
      loadFolders(item.id, item.path);
      // Auto-select the folder for import
      onSelect(item);
    }
  };

  const navigateTo = (index: number) => {
    if (index < navigationStack.length - 1) {
      navigationStack = navigationStack.slice(0, index + 1);
      const target = navigationStack[index];
      currentFolderId = target.folderId;
      loadFolders(target.folderId, target.path);
      // Select the folder we navigated back to (or site root if index 0)
      if (index === 0) {
        handleImportEntireSite();
      } else {
        onSelect({
          id: target.folderId ?? "",
          name: target.name,
          type: "folder",
          path: target.path,
          has_children: true
        });
      }
    }
  };

  const handleImportEntireSite = () => {
    onSelect({
      id: "",
      name: siteName,
      type: "site_root",
      path: "/",
      has_children: true
    });
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
          <button
            type="button"
            class="flex items-center gap-2 px-3 py-1.5 cursor-pointer text-left w-full border-b border-default transition-colors
              {selectedItemId === '' ? 'bg-accent-dimmer border-accent' : 'hover:bg-hover-default'}"
            onclick={handleImportEntireSite}
          >
            <div class="w-3.5"></div>
            {#if isOneDrive}
              <IconUploadCloud class="w-4 h-4 flex-shrink-0 text-secondary" />
            {:else}
              <IconWeb class="w-4 h-4 flex-shrink-0 text-secondary" />
            {/if}
            <span class="text-sm font-medium">Import entire {isOneDrive ? "OneDrive" : "site"}</span>
          </button>
        {/if}

        {#each currentItems as item (item.id)}
          <SharePointFolderTreeNode
            node={item}
            isSelected={selectedItemId === item.id}
            onSelect={handleNodeSelect}
            onNavigate={handleNodeNavigate}
          />
        {/each}
      </div>
    {/if}
  </div>
</div>
