<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { SOURCE_FILTERS, type SourceFilter } from "$lib/features/integrations/sources";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    counts: Record<SourceFilter, number>;
    value: SourceFilter;
  }

  let { counts, value = $bindable() }: Props = $props();

  function label(filter: SourceFilter, count: number): string {
    switch (filter) {
      case "all":
        return m.integration_filter_all({ count });
      case "attention":
        return m.integration_filter_attention({ count });
      case "syncing":
        return m.integration_filter_syncing({ count });
      case "never":
        return m.integration_filter_never({ count });
      case "empty":
        return m.integration_filter_empty({ count });
      case "ok":
        return m.integration_filter_ok({ count });
    }
  }

  // A filter emptied while it has focus stays until focus leaves, or focus would fall to the body.
  let focused = $state<SourceFilter | null>(null);

  // A filter with nothing in it is noise, unless it is the one chosen.
  let shown = $derived(
    SOURCE_FILTERS.filter(
      (filter) => filter === "all" || filter === value || filter === focused || counts[filter] > 0
    )
  );
</script>

<div role="group" aria-label={m.integration_filter_label()} class="flex flex-wrap gap-2">
  {#each shown as filter (filter)}
    <Button
      size="sm"
      variant={value === filter ? "default" : "outline"}
      aria-pressed={value === filter}
      class="rounded-full"
      onclick={() => (value = filter)}
      onfocus={() => (focused = filter)}
      onblur={() => {
        if (focused === filter) focused = null;
      }}
    >
      {label(filter, counts[filter])}
    </Button>
  {/each}
</div>
