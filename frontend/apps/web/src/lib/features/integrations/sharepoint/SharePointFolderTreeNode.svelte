<script lang="ts">
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { IconFolder } from "@intric/icons/folder";
  import { IconFile } from "@intric/icons/file";
  import { IconFileText } from "@intric/icons/file-text";
  import { IconFileImage } from "@intric/icons/file-image";
  import { IconFileAudio } from "@intric/icons/file-audio";

  type TreeNode = {
    id: string;
    name: string;
    type: "file" | "folder" | "site_root";
    path: string;
    has_children: boolean;
    size?: number;
    modified?: string;
  };

  interface Props {
    node: TreeNode;
    isSelected?: boolean;
    onSelect?: (node: TreeNode) => void;
    onNavigate?: (node: TreeNode) => void;
  }

  let {
    node,
    isSelected = false,
    onSelect,
    onNavigate
  }: Props = $props();

  const handleClick = () => {
    if (node.type === "folder") {
      onNavigate?.(node);
    } else {
      onSelect?.(node);
    }
  };

  function formatSize(bytes?: number): string {
    if (bytes == null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatDate(dateStr?: string): string {
    if (!dateStr) return "";
    const date = new Date(dateStr);
    return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "svg", "bmp", "webp", "ico", "tiff"];
  const AUDIO_EXTENSIONS = ["mp3", "wav", "ogg", "flac", "aac", "wma", "m4a"];
  const TEXT_EXTENSIONS = [
    "doc", "docx", "pdf", "txt", "rtf", "odt", "xls", "xlsx", "csv",
    "ppt", "pptx", "md", "html", "xml", "json"
  ];

  function getFileExtension(name: string): string {
    const parts = name.split(".");
    return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
  }
</script>

<button
  type="button"
  class="flex items-center gap-2 px-3 py-1.5 cursor-pointer text-left w-full border-b border-dimmer last:border-b-0 transition-colors
    {isSelected ? 'bg-accent-dimmer border-accent' : 'hover:bg-hover-default'}"
  onclick={handleClick}
>
  <!-- Chevron for folders -->
  {#if node.type === "folder"}
    <IconChevronRight class="w-3.5 h-3.5 flex-shrink-0 text-secondary" />
  {:else}
    <div class="w-3.5"></div>
  {/if}

  <!-- Icon -->
  {#if node.type === "folder"}
    <IconFolder class="w-4 h-4 flex-shrink-0 text-secondary" />
  {:else}
    {@const ext = getFileExtension(node.name)}
    {#if IMAGE_EXTENSIONS.includes(ext)}
      <IconFileImage class="w-4 h-4 flex-shrink-0 text-secondary" />
    {:else if AUDIO_EXTENSIONS.includes(ext)}
      <IconFileAudio class="w-4 h-4 flex-shrink-0 text-secondary" />
    {:else if TEXT_EXTENSIONS.includes(ext)}
      <IconFileText class="w-4 h-4 flex-shrink-0 text-secondary" />
    {:else}
      <IconFile class="w-4 h-4 flex-shrink-0 text-secondary" />
    {/if}
  {/if}

  <!-- Name -->
  <span class="truncate text-sm flex-1">{node.name}</span>

  <!-- Metadata -->
  <span class="text-xs text-secondary flex-shrink-0 tabular-nums">
    {#if node.type === "folder" && node.has_children}
      <!-- could show child count if available -->
    {:else if node.size != null}
      {formatSize(node.size)}
    {/if}
  </span>
  {#if node.modified}
    <span class="text-xs text-secondary flex-shrink-0 tabular-nums">
      {formatDate(node.modified)}
    </span>
  {/if}
</button>
