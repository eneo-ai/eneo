<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts" generics="Resource">
  import { untrack, type Snippet } from "svelte";
  import { writable } from "svelte/store";
  import type { Icon } from "@eneo/icons";
  import { IconList } from "@eneo/icons/list";
  import { IconSquares } from "@eneo/icons/squares";
  import { Button } from "$lib/components/ui/button/index.js";
  import { FlexRender } from "$lib/components/ui/data-table/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";
  import {
    ACTION_COLUMN_ID,
    CARD_COLUMN_ID,
    getCardColumn,
    setTableContext,
    type ResourceTableViewModel
  } from "./create.js";
  import EmptyState from "./EmptyState.svelte";
  import Group from "./Group.svelte";
  import SortButton from "./SortButton.svelte";

  type Props = {
    viewModel: ResourceTableViewModel<Resource>;
    displayAs?: "cards" | "list";
    /** Horizontal gap in `rem` in the card layout */
    gapX?: string | number;
    /** Vertical gap in `rem` in the card layout */
    gapY?: string | number;
    layout?: "flex" | "grid";
    /** Use when the table sits in a clearly outlined area: pads the filter bar symmetrically. */
    fitted?: boolean;
    filter?: boolean;
    resourceName?: string;
    /** Left padding of the action column; use "tight" when the table sits in a narrow place. */
    actionPadding?: "regular" | "tight";
    emptyMessage?: string;
    emptyIcon?: Icon;
    /** Render the groups even when there are no rows, e.g. so items can still be added. */
    showEmptyGroups?: boolean;
    children?: Snippet;
  };

  let {
    viewModel,
    displayAs = "list",
    gapX = "2",
    gapY = "2",
    layout = "flex",
    fitted = false,
    filter = true,
    resourceName = "item",
    actionPadding = "regular",
    emptyMessage,
    emptyIcon,
    showEmptyGroups = false,
    children
  }: Props = $props();

  // The view model and layout are fixed for the lifetime of the table, as before.
  const { displayType, headers, rows, sortKeys, filterValue, showCardSwitch } = untrack(() => {
    const displayType = writable<"cards" | "list">(displayAs);
    setTableContext({ displayType, viewModel, gapX, gapY, layout });
    return {
      displayType,
      headers: viewModel.headers,
      rows: viewModel.pageRows,
      sortKeys: viewModel.pluginStates.sort.sortKeys,
      filterValue: viewModel.pluginStates.tableFilter?.filterValue ?? writable(""),
      showCardSwitch: getCardColumn(viewModel) !== undefined
    };
  });

  const ariaSort = { asc: "ascending", desc: "descending", none: "none" } as const;
</script>

<div class="flex w-full flex-col">
  <div class={cn("flex items-center justify-between gap-4 pt-3.5 pr-3 pb-1", fitted && "pl-3")}>
    {#if filter}
      <Input
        bind:value={$filterValue}
        aria-label={m.ui_filter()}
        placeholder={m.ui_filter_items({ resourceName })}
        class="flex-grow px-4"
      />
    {/if}

    <div class="flex justify-stretch gap-1 rounded-xl">
      <Button
        variant="ghost"
        aria-pressed={$displayType === "list"}
        class="aria-pressed:bg-accent-dimmer aria-pressed:text-accent-stronger aria-pressed:font-medium"
        onclick={() => ($displayType = "list")}
      >
        <IconList />
        {m.list()}
      </Button>
      {#if showCardSwitch}
        <Button
          variant="ghost"
          aria-pressed={$displayType === "cards"}
          class="aria-pressed:bg-accent-dimmer aria-pressed:text-accent-stronger aria-pressed:font-medium"
          onclick={() => ($displayType = "cards")}
        >
          <IconSquares />
          {m.cards()}
        </Button>
      {/if}
    </div>
  </div>
  <div class="w-full">
    {#if $rows.length > 0 || showEmptyGroups}
      {#if $displayType === "list"}
        <table class="w-full border-separate border-spacing-0 text-sm">
          <thead class="bg-frosted-glass-primary sticky top-0 z-30">
            <tr>
              {#each $headers as header (header.id)}
                {#if header.column.id !== CARD_COLUMN_ID}
                  {@const isAction = header.column.id === ACTION_COLUMN_ID}
                  {@const order = $sortKeys.find((key) => key.id === header.column.id)?.order}
                  <th
                    class={cn(
                      "border-default h-14 border-b px-2 text-left font-medium",
                      isAction || header.column.id === "select" ? "w-[1%]" : "w-[10%]"
                    )}
                    aria-sort={header.column.getCanSort() ? ariaSort[order ?? "none"] : undefined}
                  >
                    <SortButton
                      {order}
                      sortable={header.column.getCanSort()}
                      onToggle={() => viewModel.toggleSort(header.column.id)}
                      actionPadding={isAction ? actionPadding : undefined}
                    >
                      <FlexRender
                        content={header.column.columnDef.header}
                        context={header.getContext()}
                      />
                    </SortButton>
                  </th>
                {/if}
              {/each}
            </tr>
          </thead>
          {#if children}
            {@render children()}
          {:else}
            <Group />
          {/if}
        </table>
      {:else}
        <div class="card-container">
          {#if children}
            {@render children()}
          {:else}
            <Group />
          {/if}
        </div>
      {/if}
    {:else}
      <div
        class="pointer-events-none absolute inset-0 flex min-h-[500px] items-center justify-center"
      >
        <EmptyState filterValue={$filterValue} {resourceName} {emptyMessage} {emptyIcon} />
      </div>
    {/if}
  </div>
</div>
