<script lang="ts">
  import type { Tokens } from "marked";

  export let token: Tokens.Heading;
</script>

<svelte:element this={`h${token.depth}`}>
  <slot />
</svelte:element>
