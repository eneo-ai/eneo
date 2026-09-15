<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Tooltip } from "@eneo/ui";
  import {
    loadLucideIconOrNull,
    type LucideIconComponent
  } from "$lib/features/templates/lucideIcons";

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
  let IconComponent = $state<LucideIconComponent | null>(null);
  $effect(() => {
    const name = iconName;
    let stale = false;
    void loadLucideIconOrNull(name).then((icon) => {
      if (!stale) IconComponent = icon;
    });
    return () => {
      stale = true;
    };
  });
</script>

<div class="flex flex-col gap-1 py-1">
  <div class="flex items-center gap-2">
    {#if iconName}
      <div class="border-strong bg-subtle flex h-6 w-6 items-center justify-center rounded border">
        {#if IconComponent}
          <IconComponent class="text-text h-4 w-4" />
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
      <Tooltip text={description} placement="bottom">
        <span class="text-dimmer line-clamp-1 max-w-[40ch] text-sm break-all">
          {description}
        </span>
      </Tooltip>
    {:else}
      <span class="text-dimmer line-clamp-1 text-sm break-all">
        {description}
      </span>
    {/if}
  {/if}
</div>
