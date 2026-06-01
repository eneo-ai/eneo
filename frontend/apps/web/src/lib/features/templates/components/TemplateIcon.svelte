<script lang="ts">
  import { dynamicColour } from "$lib/core/colours";
  import { getTemplateIconComponent } from "$lib/features/templates/templateIconRegistry";

  let {
    template,
    size = "medium"
  }: {
    template: { name: string; category: string; icon_name?: string | null };
    size?: "medium" | "large";
  } = $props();

  const IconComponent = $derived.by(() => {
    if (!template.icon_name) return null;
    return getTemplateIconComponent(template.icon_name);
  });
</script>

<div
  {...dynamicColour({ basedOn: template.category })}
  class="border-dynamic-stronger bg-dynamic-dimmer flex items-center justify-center rounded-lg border {size}"
>
  {#if IconComponent}
    <IconComponent class="text-dynamic-stronger {size === 'large' ? 'h-5 w-5' : 'h-4 w-4'}" />
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
