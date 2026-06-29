<script lang="ts">
  import { IconLinkExternal } from "@intric/icons/link-external";
  import type { Tokens } from "marked";
  import { sanitizeLinkHref } from "../sanitizeUrl.js";

  export let token: Tokens.Link;

  // Markdown can come from untrusted sources; block dangerous URL schemes
  // (e.g. javascript:) so the href is never a live script vector.
  $: safeHref = sanitizeLinkHref(token.href);
</script>

{#if safeHref}
  <!-- eslint-disable svelte/no-navigation-without-resolve -- external URL from markdown token -->
  <a
    href={safeHref}
    title={token.title}
    target="_blank"
    rel="noreferrer"
    class="hover:bg-hover-default"
  >
    <slot />
    <IconLinkExternal class="inline -translate-y-[3px] scale-[0.9]"></IconLinkExternal>
  </a>
  <!-- eslint-enable svelte/no-navigation-without-resolve -->
{:else}
  <!-- Unsafe URL scheme stripped; render the link text inert. -->
  <span title={token.title}><slot /></span>
{/if}
