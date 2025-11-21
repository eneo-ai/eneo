<script lang="ts">
  import { dynamicColour } from "$lib/core/colours";
  import * as LucideIcons from 'lucide-svelte';

  let { template, size = "medium" }: { template: { name: string; category: string; icon_name?: string | null }; size?: "medium" | "large" } = $props();

  // Convert kebab-case to PascalCase for icon lookup
  function toPascalCase(str: string): string {
    return str.charAt(0).toUpperCase() + str.slice(1).replace(/-([a-z])/g, (g) => g[1].toUpperCase());
  }

  // Get the Lucide icon component by name
  const IconComponent = $derived.by(() => {
    if (!template.icon_name) return null;
    const pascalName = toPascalCase(template.icon_name);
    return (LucideIcons as any)[pascalName] || null;
  });
</script>

<div
  {...dynamicColour({ basedOn: template.category })}
  class="border-dynamic-stronger bg-dynamic-dimmer flex items-center justify-center rounded-lg border {size}"
>
  {#if IconComponent}
    {@render IconComponent({ class: `text-dynamic-stronger ${size === 'large' ? 'h-5 w-5' : 'h-4 w-4'}` })}
  {:else}
    <span class="text-dynamic-stronger">{[...template.name][0]}</span>
  {/if}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  .medium {
    @apply h-7 w-7 min-w-7 text-lg font-medium;
  }
  .large {
    @apply h-9 w-9 min-w-9 text-2xl font-extrabold;
  }
</style>
