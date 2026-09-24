<script lang="ts">
  import type { Tokens } from "marked";
  import { sanitizeImageSrc } from "../sanitizeUrl.js";

  export let token: Tokens.Image;

  // Only http(s) and image data: URIs reach <img src>; everything else
  // (javascript:, data:text/html, …) is dropped.
  $: safeSrc = sanitizeImageSrc(token.href);
</script>

{#if safeSrc}
  <img src={safeSrc} title={token.title} alt={token.text} class="markdown-image" />
{:else}
  <!-- Unsafe image URL scheme stripped; show the alt text instead. -->
  <span class="markdown-image-fallback">{token.text}</span>
{/if}

<style>
  .markdown-image {
    max-width: 100%;
  }
</style>
