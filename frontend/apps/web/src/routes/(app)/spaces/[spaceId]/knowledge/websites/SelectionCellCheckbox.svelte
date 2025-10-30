<script lang="ts">
  import { Input } from "@intric/ui";
  import type { Writable } from "svelte/store";

  export let websiteId: string;
  export let websiteName: string;
  export let selectedWebsiteIds: Writable<Set<string>>;
  export let onToggle: (id: string) => void;

  $: checked = $selectedWebsiteIds.has(websiteId);
</script>

<Input.Checkbox
  checked={checked}
  onCheckedChange={() => onToggle(websiteId)}
  ariaLabel={`Select ${websiteName}`}
/>
