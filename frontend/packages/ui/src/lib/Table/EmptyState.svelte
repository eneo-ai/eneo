<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { ComponentType, SvelteComponent } from "svelte";
  import { getUIMessage } from "$lib/utils/messages.js";

  export let filterValue = "";
  export let resourceName = "item";
  export let emptyMessage: string | undefined = undefined;
  export let emptyIcon:
    | ComponentType<SvelteComponent<{ size?: "small" | "base" | "large"; class?: string }>>
    | undefined = undefined;
</script>

<div class="text-secondary flex flex-col items-center justify-center gap-2">
  {#if emptyIcon}
    <svelte:component this={emptyIcon} size="large" class="h-24 w-24"></svelte:component>
  {:else}
    <svg
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      stroke-width="1"
      stroke="currentColor"
      class="h-24 w-24 opacity-20"
    >
      <path
        stroke-linecap="round"
        stroke-linejoin="round"
        d="M3.75 9.776c.112-.017.227-.026.344-.026h15.812c.117 0 .232.009.344.026m-16.5 0a2.25 2.25 0 0 0-1.883 2.542l.857 6a2.25 2.25 0 0 0 2.227 1.932H19.05a2.25 2.25 0 0 0 2.227-1.932l.857-6a2.25 2.25 0 0 0-1.883-2.542m-16.5 0V6A2.25 2.25 0 0 1 6 3.75h3.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 0 1.06.44H18A2.25 2.25 0 0 1 20.25 9v.776"
      />
    </svg>
  {/if}
  {#if filterValue === ""}
    {emptyMessage ??
      getUIMessage("ui_no_items_configured", { count: 0, resourceNamePlural: resourceName })}
  {:else}
    {getUIMessage("ui_no_items_matching", { count: 0, resourceNamePlural: resourceName })}
  {/if}
</div>
