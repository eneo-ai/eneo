<script lang="ts">
  import { X } from "@lucide/svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import { activeFacets, facetValueLabel, withFacet } from "./filterFacets";
  import type { SharePointFilterColumn } from "./treeState";

  /** The chosen column filters as chips a person can remove one at a time. */
  let {
    columns,
    facets,
    onChange
  }: {
    columns: SharePointFilterColumn[];
    facets: Record<string, string>;
    onChange: (facets: Record<string, string>) => void;
  } = $props();

  const active = $derived(activeFacets(columns, facets));
  const labels = $derived({ yes: m.yes(), no: m.no() });
</script>

{#if active.length > 0}
  <ul class="flex flex-wrap items-center gap-1.5" aria-label={m.sharepoint_filters_active()}>
    {#each active as entry (entry.column.name)}
      <li>
        <Badge variant="secondary" class="h-7 gap-1 pr-1 pl-2.5 text-xs">
          <span class="text-muted-foreground">{entry.column.label}:</span>
          <span class="font-medium">{facetValueLabel(entry.column, entry.value, labels)}</span>
          <button
            type="button"
            class="hover:bg-muted focus-visible:ring-ring/50 inline-flex size-5 items-center justify-center rounded-full outline-none focus-visible:ring-[3px]"
            aria-label={m.sharepoint_filter_remove({ column: entry.column.label })}
            onclick={() => onChange(withFacet(facets, entry.column.name, ""))}
          >
            <X class="size-3.5" aria-hidden="true" />
          </button>
        </Badge>
      </li>
    {/each}
  </ul>
{/if}
