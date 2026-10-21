<script lang="ts">
  import type { Tokens } from "marked";
  import type { Snippet } from "svelte";

  let { token, children }: { token: Tokens.ListItem; children?: Snippet } = $props();
</script>

{#if token.task}
  <!-- A task item: the box takes the bullet's place and shows the state only. -->
  <li class="-ms-[1.5em] flex list-none items-start gap-[0.5em]">
    <input
      type="checkbox"
      checked={token.checked ?? false}
      disabled
      class="accent-accent-default mt-[0.35em] size-[1em] shrink-0"
    />
    <span class="min-w-0 flex-1">{@render children?.()}</span>
  </li>
{:else}
  <li>{@render children?.()}</li>
{/if}
