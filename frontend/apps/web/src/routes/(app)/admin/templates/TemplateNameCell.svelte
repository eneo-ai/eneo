<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { loadLucideIconOrNull, type LucideIconData } from "$lib/features/templates/lucideIcons";
  import LucideSvg from "$lib/features/templates/components/LucideSvg.svelte";

  interface Props {
    name: string;
    description?: string;
    isDefault?: boolean;
    iconName?: string | null;
  }

  let { name, description, isDefault = false, iconName }: Props = $props();

  // Show tooltip only for long descriptions that would be truncated
  const showTooltip = $derived(description && description.length > 80);

  // Icons resolve on demand from the lazily loaded registry (lucideIcons.ts).
  let icon = $state<LucideIconData | null>(null);
  $effect(() => {
    const name = iconName;
    let stale = false;
    void loadLucideIconOrNull(name).then((loaded) => {
      if (!stale) icon = loaded;
    });
    return () => {
      stale = true;
    };
  });
</script>

<div class="flex flex-col gap-1 py-1">
  <div class="flex items-center gap-2">
    {#if iconName}
      <div
        class="border-stronger bg-subtle flex h-6 w-6 items-center justify-center rounded border"
      >
        {#if icon}
          <LucideSvg {icon} class="text-default h-4 w-4" />
        {/if}
      </div>
    {/if}
    <span class="text-default font-medium">{name}</span>
    {#if isDefault}
      <span
        class="border-positive-stronger text-positive-stronger cursor-default rounded-full border px-2 py-0.5 text-xs font-medium"
      >
        {m.default_model()}
      </span>
    {/if}
  </div>
  {#if description}
    {#if showTooltip}
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <span {...props} class="text-muted line-clamp-1 max-w-[40ch] text-sm break-all">
              {description}
            </span>
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content side="bottom">{description}</Tooltip.Content>
      </Tooltip.Root>
    {:else}
      <span class="text-muted line-clamp-1 text-sm break-all">
        {description}
      </span>
    {/if}
  {/if}
</div>
