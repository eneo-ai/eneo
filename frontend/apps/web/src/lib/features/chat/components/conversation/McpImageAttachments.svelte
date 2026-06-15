<script lang="ts">
  import { getMessageContext } from "../../MessageContext.svelte";
  import AsyncImage from "$lib/components/AsyncImage.svelte";
  import { sanitizeImageSrc } from "@intric/ui/components/markdown";

  const { current } = getMessageContext();

  // Display-only image references: MCP `resource_link` blocks whose mimeType is
  // image/* (MCP spec, 2025-11-25). They carry no citable text, so they are not
  // rendered via the <inref> markdown path; they surface here as an attachment
  // strip below the answer. Inline markdown images for the same object are
  // de-duplicated server-side, so this strip never doubles an image already
  // shown in the answer text.
  const images = $derived(
    (current().mcp_tool_references ?? []).filter(
      (ref) => (ref.mime_type ?? "").startsWith("image/") && sanitizeImageSrc(ref.uri) !== undefined
    )
  );
</script>

{#if images.length > 0}
  <div class="flex flex-wrap gap-2 pt-2">
    {#each images as image (image.id)}
      <div class="max-w-[20rem] overflow-clip rounded-lg border shadow-md">
        <AsyncImage url={image.uri} fixedAspectRatio={false}></AsyncImage>
      </div>
    {/each}
  </div>
{/if}
