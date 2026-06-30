<!--
    Reusable server-side pagination controls.

    Displays: ← page / totalPages → | "Visar X–Y av Z"

    Usage:
      <ServerPagination
        page={pagination.page}
        totalPages={pagination.total_pages}
        totalCount={pagination.total_count}
        pageSize={pagination.page_size}
        hasNext={pagination.has_next}
        hasPrevious={pagination.has_previous}
        on:change={(e) => goToPage(e.detail)}
      />
-->
<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { Button } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";

  export let page: number;
  export let totalPages: number;
  export let totalCount: number;
  export let pageSize: number;
  export let hasNext: boolean;
  export let hasPrevious: boolean;

  const dispatch = createEventDispatcher<{ change: number }>();

  $: rangeStart = (page - 1) * pageSize + 1;
  $: rangeEnd = Math.min(page * pageSize, totalCount);
</script>

{#if totalPages > 1}
  <div class="mt-4 flex items-center gap-4">
    <div class="bg-hover-dimmer flex h-12 w-fit items-center gap-6 rounded-lg border p-2">
      <Button
        variant="outlined"
        disabled={!hasPrevious}
        on:click={() => dispatch("change", page - 1)}
      >
        ←
      </Button>
      <div class="flex gap-2 font-mono">
        <span>{page}</span>
        <span>/</span>
        <span>{totalPages}</span>
      </div>
      <Button variant="outlined" disabled={!hasNext} on:click={() => dispatch("change", page + 1)}>
        →
      </Button>
    </div>
    <span class="text-secondary text-sm">
      {m.pagination_showing_range({ start: rangeStart, end: rangeEnd, total: totalCount })}
    </span>
  </div>
{/if}
