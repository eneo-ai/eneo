<script lang="ts">
  import { SvelteSet } from "svelte/reactivity";
  import Check from "@lucide/svelte/icons/check";
  import Circle from "@lucide/svelte/icons/circle";
  import Clock from "@lucide/svelte/icons/clock";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import X from "@lucide/svelte/icons/x";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import SourceTreeNav from "$lib/features/knowledge/components/SourceTreeNav.svelte";
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
    /** Folders whose queued sync no worker has reported on yet. */
    queued: ReadonlySet<string>;
    /** Null selects the overview of every folder. */
    selectedId: string | null;
    hrefFor: (itemId: string | null) => string;
  }

  let { items, progress, queued, selectedId, hrefFor }: Props = $props();

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
    ).map((row) => ({
      ...row,
      id: row.item.id,
      name: row.item.name,
      title: row.item.folder_path ?? row.item.name
    }))
  );
  let totalDocuments = $derived(
    items.reduce((sum, item) => sum + (item.metadata?.document_count ?? 0), 0)
  );

  // A shape per state, so the state does not rest on colour alone.
  const stateIcons: Record<ItemState, { icon: typeof Check; class: string }> = {
    ok: { icon: Check, class: "text-positive-default" },
    error: { icon: X, class: "text-negative-default" },
    syncing: { icon: LoaderCircle, class: "text-accent-default motion-safe:animate-spin" },
    queued: { icon: Clock, class: "text-accent-default" },
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
      case "queued":
        return m.integration_source_state_queued();
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
</script>

<SourceTreeNav
  title={m.integration_source_folders()}
  allLabel={m.integration_source_all_folders()}
  total={totalDocuments}
  {rows}
  {selectedId}
  {hrefFor}
  ontoggle={toggle}
  filterLabel={items.length > FILTER_FROM ? m.integration_source_filter_folders() : undefined}
  bind:query
  hint={m.integration_source_subfolders_included()}
>
  {#snippet leading(row)}
    {@const state = itemState(row.item, progress, queued)}
    {@const StateIcon = stateIcons[state].icon}
    <StateIcon class="size-3.5 shrink-0 {stateIcons[state].class}" aria-hidden="true" />
  {/snippet}
  {#snippet trailing(row)}
    {@const state = itemState(row.item, progress, queued)}
    <span class="sr-only">, {stateLabel(state)}</span>
    <span
      class="text-xs tabular-nums {state === 'syncing' ? 'text-accent-stronger' : 'text-secondary'}"
      >{countLabel(row.item, state)}</span
    >
  {/snippet}
</SourceTreeNav>
