<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { Snippet } from "svelte";
  import { IconSortAsc } from "@eneo/icons/sort-asc";
  import { IconSortAscDesc } from "@eneo/icons/sort-asc-desc";
  import { IconSortDesc } from "@eneo/icons/sort-desc";
  import { Button } from "$lib/components/ui/button/index.js";
  import { cn } from "$lib/utils.js";

  type Props = {
    order: "asc" | "desc" | undefined;
    sortable: boolean;
    onToggle: () => void;
    actionPadding?: "regular" | "tight";
    children?: Snippet;
  };

  let { order, sortable, onToggle, actionPadding, children }: Props = $props();
</script>

{#if sortable}
  <Button variant="ghost" class="group font-medium" onclick={onToggle}>
    {@render children?.()}
    {#if order === "desc"}
      <IconSortDesc size="sm" />
    {:else if order === "asc"}
      <IconSortAsc size="sm" />
    {:else}
      <IconSortAscDesc size="sm" class="group-hover:text-primary text-transparent" />
    {/if}
  </Button>
{:else}
  <div class={cn("min-w-12 px-2", actionPadding === "regular" && "pl-20")}>
    {@render children?.()}
  </div>
{/if}
