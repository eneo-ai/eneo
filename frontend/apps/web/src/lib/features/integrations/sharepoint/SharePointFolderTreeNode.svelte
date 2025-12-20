<script lang="ts">
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { IconFolder } from "@intric/icons/folder";
  import { IconFile } from "@intric/icons/file";

  type TreeNode = {
    id: string;
    name: string;
    type: "file" | "folder";
    path: string;
    has_children: boolean;
    size?: number;
    modified?: string;
  };

  interface Props {
    node: TreeNode;
    level?: number;
    isExpanded?: boolean;
    onToggle?: (nodeId: string) => void;
    onSelect?: (node: TreeNode) => void;
    onNavigate?: (node: TreeNode) => void;
    isLoading?: boolean;
  }

  let {
    node,
    level = 0,
    isExpanded = false,
    onToggle,
    onSelect,
    onNavigate,
    isLoading = false
  }: Props = $props();

  const handleToggle = () => {
    onToggle?.(node.id);
  };

  const handleSelect = () => {
    onSelect?.(node);
  };

  const handleNavigate = (e: MouseEvent) => {
    e.stopPropagation();
    if (node.type === "folder") {
      onNavigate?.(node);
    }
  };
</script>

<div class="flex flex-col">
  <button
    type="button"
    class="flex items-center gap-2 px-2 py-1 hover:bg-hover-default rounded-md cursor-pointer group text-left w-full"
    style="padding-left: {level * 16 + 8}px"
    ondblclick={handleNavigate}
    onclick={handleSelect}
  >
    {#if node.has_children}
      <button
        onclick={(e) => {
          e.stopPropagation();
          handleToggle();
        }}
        class="flex-shrink-0 w-5 h-5 flex items-center justify-center transition-transform"
        class:rotate-90={isExpanded}
      >
        <IconChevronRight class="w-4 h-4" />
      </button>
    {:else}
      <div class="w-5 h-5"></div>
    {/if}

    {#if node.type === "folder"}
      <IconFolder class="w-4 h-4 flex-shrink-0 text-secondary" />
    {:else}
      <IconFile class="w-4 h-4 flex-shrink-0 text-secondary" />
    {/if}

    <span class="truncate text-sm group-hover:font-medium">{node.name}</span>

    {#if isLoading && isExpanded}
      <span class="text-xs text-muted ml-auto">Loading...</span>
    {/if}
  </button>
</div>
