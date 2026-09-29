<script lang="ts">
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { Writable } from "svelte/store";

  export let selectedWebsiteIds: Writable<Set<string>>;
  export let websites: { id: string }[];
  export let onToggleAll: () => void;

  $: isAllSelected = $selectedWebsiteIds.size > 0 && $selectedWebsiteIds.size === websites.length;
  $: isSomeSelected = $selectedWebsiteIds.size > 0 && $selectedWebsiteIds.size < websites.length;
</script>

<Checkbox
  checked={isAllSelected}
  indeterminate={isSomeSelected}
  onCheckedChange={onToggleAll}
  aria-label={m.websites_select_all()}
/>
