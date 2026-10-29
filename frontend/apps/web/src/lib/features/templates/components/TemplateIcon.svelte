<script lang="ts">
  import { dynamicColour } from "$lib/core/colours";
  import { loadLucideIconOrNull, type LucideIconData } from "../lucideIcons";
  import LucideSvg from "./LucideSvg.svelte";

  let {
    template,
    size = "medium"
  }: {
    template: { name: string; category: string; icon_name?: string | null };
    size?: "medium" | "large";
  } = $props();

  // The icon registry is fetched on demand (see lucideIcons.ts). The box keeps
  // its size while the icon is on its way, so nothing shifts when it lands;
  // the initial is shown when there is no icon to wait for, or none arrived.
  let icon = $state<LucideIconData | null>(null);
  let settled = $state(false);
  $effect(() => {
    const name = template.icon_name;
    let stale = false;
    settled = false;
    void loadLucideIconOrNull(name).then((loaded) => {
      if (stale) return;
      icon = loaded;
      settled = true;
    });
    return () => {
      stale = true;
    };
  });
</script>

<div
  {...dynamicColour({ basedOn: template.category })}
  class="border-dynamic-stronger bg-dynamic-dimmer flex items-center justify-center rounded-lg border {size}"
>
  {#if icon}
    <LucideSvg {icon} class="text-dynamic-stronger {size === 'large' ? 'h-5 w-5' : 'h-4 w-4'}" />
  {:else if !template.icon_name || settled}
    <span class="text-dynamic-stronger">{[...template.name][0]}</span>
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";
  .medium {
    @apply h-7 w-7 min-w-7 text-lg font-medium;
  }
  .large {
    @apply h-9 w-9 min-w-9 text-2xl font-extrabold;
  }
</style>
