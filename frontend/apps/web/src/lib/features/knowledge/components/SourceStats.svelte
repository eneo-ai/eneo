<script lang="ts">
  import type { Snippet } from "svelte";

  /**
   * The headline figures of a knowledge source (a website or an integration):
   * a bordered row of SourceStat cells, two per row on narrow screens.
   */
  let {
    columns = 4,
    children
  }: {
    columns?: 3 | 4;
    children: Snippet;
  } = $props();
</script>

<dl
  class="border-default bg-border grid grid-cols-2 gap-px overflow-hidden rounded-lg border {columns ===
  3
    ? 'lg:grid-cols-3'
    : 'lg:grid-cols-4'}"
>
  {@render children()}
</dl>
