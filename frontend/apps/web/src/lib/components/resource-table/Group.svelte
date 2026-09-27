<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts" generics="Resource">
  import type { Snippet } from "svelte";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { Button } from "$lib/components/ui/button/index.js";
  import { FlexRender } from "$lib/components/ui/data-table/index.js";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";
  import {
    ACTION_COLUMN_ID,
    CARD_COLUMN_ID,
    PRIMARY_COLUMN_ID,
    getTableContext
  } from "./create.js";

  type Props = {
    title?: string | null;
    /** Accessible name for the group toggle when the visible title is not descriptive. */
    toggleLabel?: string;
    filterFn?: (value: Resource) => boolean;
    /** Controlled open state; leave undefined to let the group manage it. */
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    showEmptyRow?: boolean;
    titlePrefix?: Snippet;
    titleSuffix?: Snippet;
    empty?: Snippet;
  };

  let {
    title,
    toggleLabel,
    filterFn = () => true,
    open,
    onOpenChange,
    showEmptyRow = true,
    titlePrefix,
    titleSuffix,
    empty
  }: Props = $props();

  const { viewModel, displayType, gapX, gapY, layout } = getTableContext<Resource>();
  const { pageRows } = viewModel;
  const { pageIndex, pageCount, hasPreviousPage, hasNextPage } = viewModel.pluginStates.page;

  let internalOpen = $state(true);
  const isOpen = $derived(open ?? internalOpen);

  function toggleOpen() {
    if (open === undefined) {
      internalOpen = !internalOpen;
      return;
    }
    onOpenChange?.(!isOpen);
  }

  const rows = $derived($pageRows.filter((row) => filterFn(row.original)));

  function cellClass(columnId: string, groupHeader = false) {
    return cn(
      "border-b px-4 pr-8 text-left font-normal whitespace-nowrap first-of-type:pr-0 last-of-type:pr-4",
      columnId === PRIMARY_COLUMN_ID
        ? "w-full max-w-[1px] overflow-hidden text-ellipsis"
        : "w-[0%]",
      groupHeader ? "border-default py-3.5 pl-2.5" : "border-dimmer",
      columnId === "select" && "w-[1%]"
    );
  }
</script>

<!-- `aria-expanded:bg-transparent` cancels the button's open-state fill: the toggle is a plain heading. -->
{#snippet groupTitle()}
  {@const visibleTitle = title?.trim()}
  <Button
    variant="ghost"
    size="icon"
    tabindex={visibleTitle ? -1 : undefined}
    aria-hidden={visibleTitle ? "true" : undefined}
    aria-expanded={visibleTitle ? undefined : isOpen}
    aria-label={visibleTitle ? undefined : toggleLabel}
    onclick={toggleOpen}
    class="font-mono font-medium aria-expanded:bg-transparent"
  >
    <IconChevronDown class={cn("w-5 transition-all", isOpen ? "rotate-0" : "-rotate-90")} />
  </Button>
  {@render titlePrefix?.()}
  {#if visibleTitle}
    <Button
      variant="ghost"
      aria-expanded={isOpen}
      aria-label={toggleLabel}
      onclick={toggleOpen}
      class="-ml-2 font-mono font-medium aria-expanded:bg-transparent"
    >
      <span>{title}</span>
    </Button>
  {/if}
{/snippet}

{#if $displayType === "list"}
  <tbody>
    {#if title}
      <tr>
        <td colspan="99" class={cellClass("", true)}>
          <div class="flex w-full items-center justify-between">
            <div class="flex items-center gap-2">
              {@render groupTitle()}
            </div>
            {@render titleSuffix?.()}
          </div>
        </td>
      </tr>
    {/if}
    {#if isOpen}
      {#if rows.length > 0}
        {#each rows as row (row.id)}
          <tr class="hover:bg-hover-dimmer relative h-16 transition-colors duration-150">
            {#each row.getVisibleCells() as cell (cell.id)}
              {#if cell.column.id !== CARD_COLUMN_ID}
                <td class={cellClass(cell.column.id)}>
                  {#if cell.column.id === ACTION_COLUMN_ID}
                    <div class="flex items-center justify-end">
                      <FlexRender
                        content={cell.column.columnDef.cell}
                        context={cell.getContext()}
                      />
                    </div>
                  {:else}
                    <FlexRender content={cell.column.columnDef.cell} context={cell.getContext()} />
                  {/if}
                </td>
              {/if}
            {/each}
          </tr>
        {/each}
      {:else if showEmptyRow}
        <tr>
          <td colspan="99" class="px-4 py-3">
            {@render empty?.()}
          </td>
        </tr>
      {/if}
    {/if}
  </tbody>
{:else}
  {#if title}
    <div
      class="border-b-default flex w-full items-center justify-between border-b pt-4 pr-4 pb-2 pl-2.5"
    >
      <div class="flex items-center gap-2">
        {@render groupTitle()}
      </div>
      {@render titleSuffix?.()}
    </div>
  {/if}
  {#if isOpen}
    {#if rows.length > 0}
      <div
        style="column-gap: {gapX}rem; row-gap: {gapY}rem;"
        class={cn(
          "mt-3 pt-2 pr-4 pb-4 pl-0.5",
          layout === "grid"
            ? "grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
            : "flex flex-wrap"
        )}
      >
        {#each rows as row (row.id)}
          {@const cell = row.getAllCells().find((cell) => cell.column.id === CARD_COLUMN_ID)}
          {#if cell}
            <FlexRender content={cell.column.columnDef.cell} context={cell.getContext()} />
          {/if}
        {/each}
      </div>
    {:else if showEmptyRow}
      <div class="px-4 py-3">
        {@render empty?.()}
      </div>
    {/if}
  {/if}
{/if}
{#snippet pager()}
  <div
    class="bg-hover-dimmer my-4 flex h-12 w-fit items-center justify-start gap-6 rounded-lg border p-2"
  >
    <Button
      variant="outline"
      disabled={!$hasPreviousPage}
      aria-label={m.aria_go_to_previous_page()}
      onclick={() => ($pageIndex -= 1)}>←</Button
    >
    <div class="flex gap-2 font-mono" aria-live="polite">
      <span class="sr-only">{m.page_x_of_y({ x: $pageIndex + 1, y: $pageCount })}</span>
      <span aria-hidden="true">{$pageIndex + 1}</span>
      <span aria-hidden="true">/</span>
      <span aria-hidden="true">{$pageCount}</span>
    </div>
    <Button
      variant="outline"
      disabled={!$hasNextPage}
      aria-label={m.aria_go_to_next_page()}
      onclick={() => ($pageIndex += 1)}>→</Button
    >
  </div>
{/snippet}

{#if rows.length > 0 && $pageCount > 1}
  {#if $displayType === "list"}
    <tbody>
      <tr>
        <td colspan="99">
          {@render pager()}
        </td>
      </tr>
    </tbody>
  {:else}
    {@render pager()}
  {/if}
{:else if title}
  <svelte:element this={$displayType === "list" ? "tbody" : "div"} class="h-6" />
{/if}
