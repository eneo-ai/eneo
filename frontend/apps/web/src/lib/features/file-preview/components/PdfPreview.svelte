<script lang="ts">
  import { browser } from "$app/environment";
  import { m } from "$lib/paraglide/messages";

  let {
    blob,
    title,
    onready,
    onerror
  }: {
    blob: Blob;
    title: string;
    onready?: () => void;
    onerror?: () => void;
  } = $props();

  // Shown by the browser's own PDF viewer. Browsers without an inline viewer
  // (most phones) would offer the frame's content as a download instead.
  const viewerAvailable = browser && navigator.pdfViewerEnabled !== false;

  $effect(() => {
    // The unsupported-viewer notice is itself the final preview on these devices.
    if (!viewerAvailable) onready?.();
  });

  const url = $derived(viewerAvailable ? URL.createObjectURL(blob) : undefined);
  $effect(() => {
    const objectUrl = url;
    if (objectUrl) return () => URL.revokeObjectURL(objectUrl);
  });
</script>

{#if !viewerAvailable}
  <p class="text-muted-foreground p-6 text-sm">{m.file_preview_unsupported_here()}</p>
{:else if url}
  <iframe
    onload={() => onready?.()}
    onerror={() => onerror?.()}
    src="{url}#navpanes=0&view=FitH"
    {title}
    class="min-h-0 w-full flex-1 border-0"
  ></iframe>
{/if}
