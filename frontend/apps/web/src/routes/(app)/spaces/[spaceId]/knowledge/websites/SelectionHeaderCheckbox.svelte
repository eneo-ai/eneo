<script lang="ts">
  import { Input } from "@eneo/ui";
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

<Input.Checkbox
  checked={isAllSelected}
  indeterminate={isSomeSelected}
  onCheckedChange={onToggleAll}
  ariaLabel={isAllSelected ? m.deselect_all() : m.select_all()}
/>
