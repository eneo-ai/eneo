<script lang="ts">
  import { Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import type { Writable } from "svelte/store";

  export let websiteId: string;
  export let websiteName: string;
  export let selectedWebsiteIds: Writable<Set<string>>;
  export let onToggle: (id: string) => void;

  $: checked = $selectedWebsiteIds.has(websiteId);
</script>

<Input.Checkbox
  {checked}
  onCheckedChange={() => onToggle(websiteId)}
  ariaLabel={m.select_website({ websiteName })}
/>
