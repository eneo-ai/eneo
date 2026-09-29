<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Icon } from "@eneo/icons";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    filterValue?: string;
    resourceName?: string;
    emptyMessage?: string;
    emptyIcon?: Icon;
  };

  let { filterValue = "", resourceName = "item", emptyMessage, emptyIcon }: Props = $props();
</script>

<div class="text-secondary flex flex-col items-center justify-center gap-2">
  {#if emptyIcon}
    {@const EmptyIcon = emptyIcon}
    <EmptyIcon size="lg" class="h-24 w-24" />
  {:else}
    <svg
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      stroke-width="1"
      stroke="currentColor"
      class="h-24 w-24 opacity-20"
      aria-hidden="true"
    >
      <path
        stroke-linecap="round"
        stroke-linejoin="round"
        d="M3.75 9.776c.112-.017.227-.026.344-.026h15.812c.117 0 .232.009.344.026m-16.5 0a2.25 2.25 0 0 0-1.883 2.542l.857 6a2.25 2.25 0 0 0 2.227 1.932H19.05a2.25 2.25 0 0 0 2.227-1.932l.857-6a2.25 2.25 0 0 0-1.883-2.542m-16.5 0V6A2.25 2.25 0 0 1 6 3.75h3.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 0 1.06.44H18A2.25 2.25 0 0 1 20.25 9v.776"
      />
    </svg>
  {/if}
  {#if filterValue === ""}
    {emptyMessage ?? m.ui_no_items_configured({ resourceNamePlural: resourceName })}
  {:else}
    {m.ui_no_items_matching({ resourceNamePlural: resourceName })}
  {/if}
</div>
