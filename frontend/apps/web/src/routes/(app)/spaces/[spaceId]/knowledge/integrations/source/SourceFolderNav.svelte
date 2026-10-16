<script lang="ts">
  import { SvelteSet } from "svelte/reactivity";
  import Check from "@lucide/svelte/icons/check";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import Circle from "@lucide/svelte/icons/circle";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import X from "@lucide/svelte/icons/x";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { Input } from "$lib/components/ui/input/index.js";
  import {
    buildIntegrationTree,
    filterIntegrationTree,
    flattenIntegrationTree
  } from "$lib/features/integrations/integrationTree";
  import { itemState, type ItemState } from "$lib/features/integrations/sources";
  import type { IntegrationSyncProgress } from "$lib/features/integrations/syncProgress";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    items: IntegrationKnowledge[];
    progress: Record<string, IntegrationSyncProgress>;
    /** Null selects the overview of every folder. */
    selectedId: string | null;
    hrefFor: (itemId: string | null) => string;
  }

  let { items, progress, selectedId, hrefFor }: Props = $props();

  /** Below this many folders the whole tree fits and a filter only adds noise. */
  const FILTER_FROM = 8;

  let query = $state("");
  const collapsed = new SvelteSet<string>();

  let tree = $derived(buildIntegrationTree(items));
  let filtering = $derived(query.trim() !== "");
  // While filtering every match is shown, so collapsed parents open up.
  let rows = $derived(
    flattenIntegrationTree(
      filterIntegrationTree(tree, query),
      (item) => filtering || !collapsed.has(item.id)
    )
  );
  let totalDocuments = $derived(
    items.reduce((sum, item) => sum + (item.metadata?.document_count ?? 0), 0)
  );

  // A shape per state, so the state does not rest on colour alone.
  const stateIcons: Record<ItemState, { icon: typeof Check; class: string }> = {
    ok: { icon: Check, class: "text-positive-default" },
    error: { icon: X, class: "text-negative-default" },
    syncing: { icon: LoaderCircle, class: "text-accent-default motion-safe:animate-spin" },
    empty: { icon: TriangleAlert, class: "text-warning-default" },
    never: { icon: Circle, class: "text-secondary" }
  };

  function stateLabel(state: ItemState): string {
    switch (state) {
      case "ok":
        return m.integration_source_state_ok();
      case "error":
        return m.integration_sync_status_error();
      case "syncing":
        return m.integration_source_state_syncing();
      case "empty":
        return m.integration_sync_status_empty();
      case "never":
        return m.integration_source_state_never();
    }
  }

  function countLabel(item: IntegrationKnowledge, state: ItemState): string {
    const entry = progress[item.id];
    if (entry) return entry.total === null ? `${entry.done}` : `${entry.done}/${entry.total}`;
    if (state === "never") return "–";
    return `${item.metadata?.document_count ?? 0}`;
  }

  function toggle(itemId: string) {
    if (collapsed.has(itemId)) collapsed.delete(itemId);
    else collapsed.add(itemId);
  }

  const linkClass =
    "focus-visible:ring-stronger flex min-h-9 min-w-0 flex-1 items-center gap-2.5 rounded-md pr-2 text-sm focus-visible:ring-2 focus-visible:outline-none";
</script>

<nav aria-label={m.integration_source_folders()} class="flex flex-col gap-1">
  <h2 class="text-secondary px-2 pb-1 text-xs font-medium tracking-wide uppercase">
    {m.integration_source_folders()}
  </h2>
  {#if items.length > FILTER_FROM}
    <Input
      type="search"
      bind:value={query}
      aria-label={m.integration_source_filter_folders()}
      placeholder={m.integration_source_filter_folders()}
      class="mb-1 h-8"
    />
  {/if}
  <ul class="flex flex-col gap-0.5">
    {#if !filtering}
      <li>
        <!-- eslint-disable svelte/no-navigation-without-resolve -- hrefs come from the caller -->
        <a
          href={hrefFor(null)}
          aria-current={selectedId === null ? "page" : undefined}
          data-sveltekit-noscroll
          data-sveltekit-replacestate
          class="{linkClass} pl-8 {selectedId === null
            ? 'bg-secondary font-medium'
            : 'hover:bg-hover-dimmer'}"
        >
          <span class="flex-1 truncate">{m.integration_source_all_folders()}</span>
          <span class="text-secondary text-xs tabular-nums">{totalDocuments}</span>
        </a>
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      </li>
    {/if}
    {#each rows as row (row.item.id)}
      {@const state = itemState(row.item, progress)}
      {@const StateIcon = stateIcons[state].icon}
      <li class="flex items-center" style:padding-left="{row.depth * 1.25}rem">
        {#if row.hasChildren && !filtering}
          <button
            type="button"
            aria-expanded={row.expanded}
            aria-label={row.expanded
              ? m.integration_source_collapse_folder({ name: row.item.name })
              : m.integration_source_expand_folder({ name: row.item.name })}
            onclick={() => toggle(row.item.id)}
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
        <!-- eslint-disable svelte/no-navigation-without-resolve -- hrefs come from the caller -->
        <a
          href={hrefFor(row.item.id)}
          aria-current={selectedId === row.item.id ? "page" : undefined}
          title={row.item.folder_path ?? row.item.name}
          data-sveltekit-noscroll
          data-sveltekit-replacestate
          class="{linkClass} pl-1 {selectedId === row.item.id
            ? 'bg-secondary font-medium'
            : 'hover:bg-hover-dimmer'}"
        >
          <StateIcon class="size-3.5 shrink-0 {stateIcons[state].class}" aria-hidden="true" />
          <span class="flex-1 truncate">{row.item.name}</span>
          <span class="sr-only">, {stateLabel(state)}</span>
          <span
            class="text-xs tabular-nums {state === 'syncing'
              ? 'text-accent-stronger'
              : 'text-secondary'}">{countLabel(row.item, state)}</span
          >
        </a>
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      </li>
    {:else}
      <li class="text-secondary px-2 py-2 text-sm">{m.no_results_found()}</li>
    {/each}
  </ul>
  <p class="text-secondary px-2 pt-2 text-xs leading-relaxed">
    {m.integration_source_subfolders_included()}
  </p>
</nav>
