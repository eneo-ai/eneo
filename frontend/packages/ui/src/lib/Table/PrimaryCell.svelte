<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button } from "$lib/Button/index.js";
  import { Tooltip } from "$lib/Tooltip/index.js";
  import type { Icon } from "@intric/icons";

  export let customClass: string = "";
  export let tooltip: string = "";
  export let label: string;
  export let link: string | undefined = undefined;
  export let icon: Icon | undefined = undefined;
</script>

<Tooltip text={tooltip} placement="top" asFragment let:trigger>
  <div class="flex w-full items-center justify-start {customClass} gap-2">
    {#if link}
      <Button
        href={link}
        is={trigger && trigger[0]}
        padding={icon ? "icon-leading" : undefined}
        class="{icon ? '-ml-1' : '-ml-2'} max-w-full"
      >
        {#if icon}
          <svelte:component this={icon} class="text-muted group-hover:text-primary min-w-6"
          ></svelte:component>
        {/if}
        <span class="truncate overflow-ellipsis">
          {label}
        </span>
      </Button>
    {:else}
      {#if icon}
        <svelte:component this={icon} class="min-w-6"></svelte:component>
      {/if}
      <button class="truncate overflow-ellipsis" type="button" {...(trigger && trigger[0] || {})}>
        {label}
      </button>
    {/if}
  </div>
</Tooltip>
