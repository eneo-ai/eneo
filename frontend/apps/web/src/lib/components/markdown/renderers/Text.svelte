<script lang="ts">
  import type { Tokens } from "marked";

  export let token: Tokens.Text;
</script>

{#if $$slots.default}
  <slot></slot>
{:else}
  {token.raw}
{/if}
