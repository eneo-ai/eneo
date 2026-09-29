<script lang="ts">
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { Readable, Writable } from "svelte/store";

  export let selectedWebsiteIds: Writable<Set<string>>;
  export let visibleWebsiteIds: Readable<string[]>;
  export let onToggleAll: () => void;

  $: selectedVisibleCount = $visibleWebsiteIds.filter((websiteId) =>
    $selectedWebsiteIds.has(websiteId)
  ).length;
  $: isAllSelected =
    $visibleWebsiteIds.length > 0 && selectedVisibleCount === $visibleWebsiteIds.length;
  $: isSomeSelected = selectedVisibleCount > 0 && !isAllSelected;
</script>

<Checkbox
  checked={isAllSelected}
  indeterminate={isSomeSelected}
  onCheckedChange={onToggleAll}
  aria-label={isAllSelected ? m.deselect_all() : m.select_all()}
/>
