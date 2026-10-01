<script lang="ts">
  import { ListFilter, Search, X } from "@lucide/svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { SharePointFilterColumn } from "./treeState";

  /**
   * Column filters for a library search. One button opens every filterable
   * column in a scrolling list, so a library with thirty columns takes the same
   * room as one with two; the chosen values sit beside the search as chips a
   * person can remove one at a time.
   */
  let {
    columns,
    facets,
    onChange
  }: {
    columns: SharePointFilterColumn[];
    /** Chosen values by column name; "" or a missing key means no filter. */
    facets: Record<string, string>;
    onChange: (facets: Record<string, string>) => void;
  } = $props();

  const COLUMN_SEARCH_THRESHOLD = 6;

  let columnSearch = $state("");
  const active = $derived(
    columns
      .map((column) => ({ column, value: facets[column.name] ?? "" }))
      .filter((entry) => entry.value !== "")
  );
  const visibleColumns = $derived.by(() => {
    const needle = columnSearch.trim().toLowerCase();
    if (!needle) return columns;
    return columns.filter((column) => column.label.toLowerCase().includes(needle));
  });

  function valueLabel(column: SharePointFilterColumn, value: string): string {
    if (column.kind === "boolean") return value === "true" ? m.yes() : m.no();
    return value;
  }

  function setFacet(name: string, value: string) {
    const next = { ...facets, [name]: value };
    if (!value) delete next[name];
    onChange(next);
  }
</script>

{#if columns.length > 0}
  <Popover.Root>
    <Popover.Trigger
      class={buttonVariants({ variant: active.length > 0 ? "secondary" : "outline" }) +
        " h-10 gap-1.5"}
      aria-label={m.sharepoint_filters_aria({ count: String(active.length) })}
    >
      <ListFilter class="size-4" aria-hidden="true" />
      <span>{m.sharepoint_filters()}</span>
      {#if active.length > 0}
        <Badge variant="default" class="ml-0.5 px-1.5 tabular-nums" aria-hidden="true">
          {active.length}
        </Badge>
      {/if}
    </Popover.Trigger>

    <Popover.Content align="start" class="w-[22rem] max-w-[calc(100vw-2rem)] gap-0 p-0">
      <div class="border-b px-3 py-2.5">
        <Popover.Title class="text-sm">{m.sharepoint_filters_title()}</Popover.Title>
        {#if columns.length > COLUMN_SEARCH_THRESHOLD}
          <InputGroup.Root class="bg-background mt-2">
            <InputGroup.Addon>
              <Search class="size-4 shrink-0 opacity-60" aria-hidden="true" />
            </InputGroup.Addon>
            <InputGroup.Input
              type="search"
              bind:value={columnSearch}
              placeholder={m.sharepoint_filters_search()}
              aria-label={m.sharepoint_filters_search()}
              autocomplete="off"
            />
          </InputGroup.Root>
        {/if}
      </div>
      <!-- Columns scroll inside the popover; the dialog behind keeps its layout. -->
      <div class="flex max-h-[50vh] flex-col gap-3 overflow-y-auto px-3 py-3">
        {#each visibleColumns as column (column.name)}
          {@const id = `sharepoint-filter-${column.name}`}
          <div class="flex flex-col gap-1">
            <label for={id} class="text-sm font-medium">{column.label}</label>
            <Select.Root
              type="single"
              value={facets[column.name] ?? ""}
              onValueChange={(value) => setFacet(column.name, value)}
            >
              <Select.Trigger {id} class="w-full">
                {facets[column.name]
                  ? valueLabel(column, facets[column.name])
                  : m.sharepoint_filter_any()}
              </Select.Trigger>
              <Select.Content>
                <Select.Item value="" label={m.sharepoint_filter_any()}>
                  {m.sharepoint_filter_any()}
                </Select.Item>
                {#if column.kind === "boolean"}
                  <Select.Item value="true" label={m.yes()}>{m.yes()}</Select.Item>
                  <Select.Item value="false" label={m.no()}>{m.no()}</Select.Item>
                {:else}
                  {#each column.choices as choice (choice)}
                    <Select.Item value={choice} label={choice}>{choice}</Select.Item>
                  {/each}
                {/if}
              </Select.Content>
            </Select.Root>
          </div>
        {:else}
          <p class="text-muted-foreground text-sm">{m.sharepoint_filters_no_column_match()}</p>
        {/each}
      </div>
      {#if active.length > 0}
        <div class="flex justify-end border-t px-3 py-2">
          <Button variant="ghost" size="sm" onclick={() => onChange({})}>
            {m.sharepoint_filters_clear()}
          </Button>
        </div>
      {/if}
    </Popover.Content>
  </Popover.Root>
{/if}

{#if active.length > 0}
  <ul class="flex flex-wrap items-center gap-1.5" aria-label={m.sharepoint_filters_active()}>
    {#each active as entry (entry.column.name)}
      <li>
        <Badge variant="secondary" class="h-7 gap-1 pr-1 pl-2.5 text-xs">
          <span class="text-muted-foreground">{entry.column.label}:</span>
          <span class="font-medium">{valueLabel(entry.column, entry.value)}</span>
          <button
            type="button"
            class="hover:bg-muted focus-visible:ring-ring/50 inline-flex size-5 items-center justify-center rounded-full outline-none focus-visible:ring-[3px]"
            aria-label={m.sharepoint_filter_remove({ column: entry.column.label })}
            onclick={() => setFacet(entry.column.name, "")}
          >
            <X class="size-3.5" aria-hidden="true" />
          </button>
        </Badge>
      </li>
    {/each}
  </ul>
{/if}
