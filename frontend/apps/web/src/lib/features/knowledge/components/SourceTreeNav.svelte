<script module lang="ts">
  export interface SourceTreeRow {
    id: string;
    name: string;
    title?: string;
    depth: number;
    hasChildren: boolean;
    expanded: boolean;
    /** Pagination and retry controls occupy their place within the branch. */
    action?: () => void;
    disabled?: boolean;
  }
</script>

<script lang="ts" generics="Row extends SourceTreeRow">
  import type { Snippet } from "svelte";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import { Input } from "$lib/components/ui/input/index.js";
  import { m } from "$lib/paraglide/messages";

  let {
    title,
    allLabel,
    total,
    rows,
    selectedId,
    hrefFor,
    ontoggle,
    onselect,
    filterLabel,
    query = $bindable(""),
    hint,
    leading,
    trailing,
    totalLabel,
    emptyLabel
  }: {
    title: string;
    allLabel: string;
    total: number;
    /** What `total` counts, read in place of the bare number by screen readers. */
    totalLabel?: string;
    rows: Row[];
    selectedId: string | null;
    hrefFor: (id: string | null) => string;
    ontoggle: (id: string) => void;
    onselect?: (id: string | null) => void;
    filterLabel?: string;
    query?: string;
    hint?: string;
    /** Shown for an empty tree while nothing is filtered; an empty string shows nothing. */
    emptyLabel?: string;
    leading?: Snippet<[Row]>;
    trailing?: Snippet<[Row]>;
  } = $props();

  function select(event: MouseEvent, id: string | null) {
    if (onselect && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      onselect(id);
    }
  }

  const linkClass =
    "focus-visible:ring-stronger flex min-h-9 min-w-0 flex-1 items-center gap-2.5 rounded-md pr-2 text-sm focus-visible:ring-2 focus-visible:outline-none";
</script>

<nav aria-label={title} class="flex min-w-0 flex-col gap-1">
  <h2 class="text-secondary px-2 pb-1 text-xs font-medium tracking-wide uppercase">{title}</h2>
  {#if filterLabel}
    <Input
      type="search"
      bind:value={query}
      aria-label={filterLabel}
      placeholder={filterLabel}
      class="mb-1 h-8"
    />
  {/if}
  <ul class="flex flex-col gap-0.5">
    {#if !query.trim()}
      <li>
        <!-- eslint-disable svelte/no-navigation-without-resolve -- hrefs come from the caller -->
        <a
          href={hrefFor(null)}
          onclick={(event) => select(event, null)}
          aria-current={selectedId === null ? "page" : undefined}
          data-sveltekit-noscroll
          data-sveltekit-replacestate
          data-sveltekit-keepfocus
          class="{linkClass} pl-8 {selectedId === null
            ? 'bg-secondary font-medium'
            : 'hover:bg-hover-dimmer'}"
        >
          <span class="flex-1 truncate">{allLabel}</span>
          {#if totalLabel}<span class="sr-only">, {totalLabel}</span>{/if}
          <span
            class="text-secondary text-xs tabular-nums"
            aria-hidden={totalLabel ? "true" : undefined}>{total}</span
          >
        </a>
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      </li>
    {/if}
    {#each rows as row (row.id)}
      <li class="flex items-center" style:padding-left="{row.depth * 1.25}rem">
        {#if row.hasChildren && !query.trim()}
          <button
            type="button"
            aria-expanded={row.expanded}
            aria-label={row.expanded
              ? m.source_tree_collapse({ name: row.name })
              : m.source_tree_expand({ name: row.name })}
            onclick={() => ontoggle(row.id)}
            class="text-secondary hover:bg-hover-dimmer focus-visible:ring-stronger flex size-7 shrink-0 items-center justify-center rounded-md focus-visible:ring-2 focus-visible:outline-none"
          >
            <ChevronRight
              class="size-4 motion-safe:transition-transform {row.expanded ? 'rotate-90' : ''}"
              aria-hidden="true"
            />
          </button>
        {:else}
          <span class="w-7 shrink-0" aria-hidden="true"></span>
        {/if}
        {#if row.action}
          <button
            type="button"
            onclick={row.action}
            disabled={row.disabled}
            class="{linkClass} text-secondary pl-1 text-left hover:underline disabled:opacity-60"
            >{row.name}</button
          >
        {:else}
          <!-- eslint-disable svelte/no-navigation-without-resolve -- hrefs come from the caller -->
          <a
            href={hrefFor(row.id)}
            onclick={(event) => select(event, row.id)}
            aria-current={selectedId === row.id ? "page" : undefined}
            title={row.title ?? row.name}
            data-sveltekit-noscroll
            data-sveltekit-replacestate
            data-sveltekit-keepfocus
            class="{linkClass} pl-1 {selectedId === row.id
              ? 'bg-secondary font-medium'
              : 'hover:bg-hover-dimmer'}"
          >
            {@render leading?.(row)}
            <span class="flex-1 truncate">{row.name}</span>
            {@render trailing?.(row)}
          </a>
          <!-- eslint-enable svelte/no-navigation-without-resolve -->
        {/if}
      </li>
    {:else}
      {@const empty = query.trim() ? m.no_results_found() : (emptyLabel ?? m.no_results_found())}
      {#if empty}<li class="text-secondary px-2 py-2 text-sm">{empty}</li>{/if}
    {/each}
  </ul>
  {#if hint}<p class="text-secondary px-2 pt-2 text-xs leading-relaxed">{hint}</p>{/if}
</nav>
