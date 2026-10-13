<script lang="ts">
  import type { Tokens } from "marked";
  import { fileHandleId, getFileImageUrls } from "../FileImageContext.js";
  import { sanitizeImageSrc } from "../sanitizeUrl.js";

  let { token }: { token: Tokens.Image } = $props();

  // A document names an image of its own by the file's handle; where the
  // surroundings can link to files, it is shown from there. The link is
  // fetched on first use, so the image appears once it has arrived.
  const fileImageUrl = getFileImageUrls();
  const fileId = $derived(fileImageUrl ? fileHandleId(token.href) : null);
  const fileSrc = $derived(fileId ? fileImageUrl?.(fileId) : undefined);

  // Only http(s) and image data: URIs reach <img src>; everything else
  // (javascript:, data:text/html, …) is dropped.
  const safeSrc = $derived(sanitizeImageSrc(token.href));
</script>

{#if fileSrc}
  <span class="markdown-figure">
    <img src={fileSrc} alt={token.text} class="markdown-image" />
    {#if token.title}
      <span class="markdown-figure-caption">{token.title}</span>
    {/if}
  </span>
{:else if fileId}
  <span class="markdown-image-fallback">{token.text}</span>
{:else if safeSrc}
  <img src={safeSrc} title={token.title} alt={token.text} class="markdown-image" />
{:else}
  <!-- Unsafe image URL scheme stripped; show the alt text instead. -->
  <span class="markdown-image-fallback">{token.text}</span>
{/if}

<style>
  .markdown-image {
    max-width: 100%;
  }

  /* Spans, because the image sits inside its paragraph. */
  .markdown-figure {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
  }

  .markdown-figure .markdown-image {
    margin: 0;
  }

  .markdown-figure-caption {
    color: var(--color-muted-foreground);
    font-size: 0.875em;
    font-style: italic;
    text-align: center;
  }
</style>
