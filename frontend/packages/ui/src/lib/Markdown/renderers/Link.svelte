<script lang="ts">
  import { IconLinkExternal } from "@intric/icons/link-external";
  import type { Tokens } from "marked";

  export let token: Tokens.Link;
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- external URL from markdown token -->
<a
  href={token.href}
  title={token.title}
  target="_blank"
  rel="noreferrer"
  class="hover:bg-hover-default"
>
  <slot />
  <IconLinkExternal class="inline -translate-y-[3px] scale-[0.9]"></IconLinkExternal>
</a>
<!-- eslint-enable svelte/no-navigation-without-resolve -->
