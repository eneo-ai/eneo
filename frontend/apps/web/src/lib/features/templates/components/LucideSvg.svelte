<script lang="ts">
  import type { LucideIconData } from "../lucideIcons";

  // Draws icon data the way @lucide/svelte's own icon components do (their
  // Icon.svelte, with its default size and stroke). That `Icon` is only
  // exported from the package's barrel, and importing the barrel makes the
  // build load every Lucide module.
  let { icon, class: className }: { icon: LucideIconData; class?: string } = $props();
</script>

<svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  class={["lucide-icon lucide", `lucide-${icon.name}`, className]}
>
  {#each icon.iconNode as [tag, attrs], index (index)}
    <svelte:element this={tag as string} {...attrs} />
  {/each}
</svg>
