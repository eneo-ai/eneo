<script lang="ts">
  import { Input } from "@intric/ui";
  import type { Writable } from "svelte/store";

  export let selectedWebsiteIds: Writable<Set<string>>;
  export let websites: any[];
  export let onToggleAll: () => void;

  $: isAllSelected = $selectedWebsiteIds.size > 0 && $selectedWebsiteIds.size === websites.length;
  $: isSomeSelected = $selectedWebsiteIds.size > 0 && $selectedWebsiteIds.size < websites.length;
</script>

<Input.Checkbox
  checked={isAllSelected}
  indeterminate={isSomeSelected}
  onCheckedChange={onToggleAll}
  ariaLabel="Select all websites"
/>
