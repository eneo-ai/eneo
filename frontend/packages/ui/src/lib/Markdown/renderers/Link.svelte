<script lang="ts">
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import type { Tokens } from "marked";

  export let token: Tokens.Link;
</script>

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
