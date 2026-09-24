<script lang="ts">
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { Writable } from "svelte/store";

  export let websiteId: string;
  export let websiteName: string;
  export let selectedWebsiteIds: Writable<Set<string>>;
  export let onToggle: (id: string) => void;

  $: checked = $selectedWebsiteIds.has(websiteId);
</script>

<Checkbox
  {checked}
  onCheckedChange={() => onToggle(websiteId)}
  aria-label={m.website_select({ name: websiteName })}
/>
