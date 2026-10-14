<script lang="ts">
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import {
    buildIntegrationTree,
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

  let rows = $derived(flattenIntegrationTree(buildIntegrationTree(items), () => true));
  let totalDocuments = $derived(
    items.reduce((sum, item) => sum + (item.metadata?.document_count ?? 0), 0)
  );

  const dotClass: Record<ItemState, string> = {
    ok: "bg-positive-default",
    error: "bg-negative-default",
    syncing: "bg-accent-default motion-safe:animate-pulse",
    empty: "bg-warning-default",
    never: "border-strongest border"
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

  const linkClass =
    "focus-visible:ring-stronger flex min-h-9 items-center gap-2.5 rounded-md pr-2 text-sm focus-visible:ring-2 focus-visible:outline-none";
</script>

<nav aria-label={m.integration_source_folders()} class="flex flex-col gap-1">
  <h2 class="text-secondary px-2 pb-1 text-xs font-medium tracking-wide uppercase">
    {m.integration_source_folders()}
  </h2>
  <ul class="flex flex-col gap-0.5">
    <li>
      <!-- eslint-disable svelte/no-navigation-without-resolve -- hrefs come from the caller -->
      <a
        href={hrefFor(null)}
        aria-current={selectedId === null ? "page" : undefined}
        data-sveltekit-noscroll
        data-sveltekit-replacestate
        class="{linkClass} pl-2 {selectedId === null
          ? 'bg-secondary font-medium'
          : 'hover:bg-hover-dimmer'}"
      >
        <span class="flex-1 truncate">{m.integration_source_all_folders()}</span>
        <span class="text-secondary text-xs tabular-nums">{totalDocuments}</span>
      </a>
    </li>
    {#each rows as row (row.item.id)}
      {@const state = itemState(row.item, progress)}
      <li>
        <a
          href={hrefFor(row.item.id)}
          aria-current={selectedId === row.item.id ? "page" : undefined}
          data-sveltekit-noscroll
          data-sveltekit-replacestate
          style:padding-left="{0.5 + row.depth * 1.25}rem"
          class="{linkClass} {selectedId === row.item.id
            ? 'bg-secondary font-medium'
            : 'hover:bg-hover-dimmer'}"
        >
          <span class="size-2 shrink-0 rounded-full {dotClass[state]}" aria-hidden="true"></span>
          <span class="flex-1 truncate">{row.item.name}</span>
          <span class="sr-only">, {stateLabel(state)}</span>
          <span
            class="text-xs tabular-nums {state === 'syncing'
              ? 'text-accent-stronger'
              : 'text-secondary'}">{countLabel(row.item, state)}</span
          >
        </a>
      </li>
    {/each}
    <!-- eslint-enable svelte/no-navigation-without-resolve -->
  </ul>
  <p class="text-secondary px-2 pt-2 text-xs leading-relaxed">
    {m.integration_source_subfolders_included()}
  </p>
</nav>
