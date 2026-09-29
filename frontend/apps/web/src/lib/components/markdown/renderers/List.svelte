<script lang="ts">
  import type { Tokens } from "marked";
  import RenderToken from "./RenderToken.svelte";

  export let token: Tokens.List;
</script>

<svelte:element this={token.ordered ? "ol" : "ul"} start={token.start || 1}>
  {#each token.items as item, i (i)}
    <RenderToken token={item}></RenderToken>
  {/each}
</svelte:element>
