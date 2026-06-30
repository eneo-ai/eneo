<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import Button from "$lib/Button/Button.svelte";
  import { IconSortAsc } from "@eneo/icons/sort-asc";
  import { IconSortAscDesc } from "@eneo/icons/sort-asc-desc";
  import { IconSortDesc } from "@eneo/icons/sort-desc";
  import type { Readable } from "svelte/store";

  export let props: Readable<{
    sort: {
      order: "desc" | "asc" | undefined;
      toggle: (event: Event) => void;
      clear: () => void;
      disabled: boolean;
    };
  }>;

  export let actionPadding: "regular" | "tight" | undefined = undefined;
</script>

{#if !$props.sort.disabled}
  <Button on:click={$props.sort.toggle}>
    <slot />
    {#if $props.sort.order === "desc"}
      <IconSortDesc size="sm" />
    {:else if $props.sort.order === "asc"}
      <IconSortAsc size="sm" />
    {:else}
      <IconSortAscDesc size="sm" class="group-hover:text-primary text-transparent" />
    {/if}
  </Button>
{:else}
  <div class="min-w-12 px-2" class:pl-20={actionPadding === "regular"}>
    <slot />
  </div>
{/if}
