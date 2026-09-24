<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Icon } from "@eneo/icons";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { cn } from "$lib/utils.js";

  type Props = {
    label: string;
    link?: string;
    icon?: Icon;
    tooltip?: string;
    customClass?: string;
  };

  let { label, link, icon, tooltip = "", customClass = "" }: Props = $props();
</script>

{#snippet linkBody()}
  {#if icon}
    {@const LinkIcon = icon}
    <LinkIcon class="text-muted group-hover:text-primary min-w-6" />
  {/if}
  <span class="truncate">{label}</span>
{/snippet}

<div class={cn("flex w-full items-center justify-start gap-2", customClass)}>
  {#if link}
    {@const linkClass = cn("group max-w-full justify-start", icon ? "-ml-1" : "-ml-2")}
    {#if tooltip}
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <Button {...props} href={link} variant="ghost" class={linkClass}>
              {@render linkBody()}
            </Button>
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content>{tooltip}</Tooltip.Content>
      </Tooltip.Root>
    {:else}
      <Button href={link} variant="ghost" class={linkClass}>
        {@render linkBody()}
      </Button>
    {/if}
  {:else}
    {#if icon}
      {@const LabelIcon = icon}
      <LabelIcon class="min-w-6" />
    {/if}
    {#if tooltip}
      <Tooltip.Root>
        <Tooltip.Trigger class="cursor-default truncate text-left">{label}</Tooltip.Trigger>
        <Tooltip.Content>{tooltip}</Tooltip.Content>
      </Tooltip.Root>
    {:else}
      <span class="truncate">{label}</span>
    {/if}
  {/if}
</div>
