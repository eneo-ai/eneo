<script lang="ts">
  import { IconCheck } from "@intric/icons/check";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { fade } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
  import { onDestroy } from "svelte";

  export let status: "saved" | "saving" | "unsaved";

  let displayedStatus: "saved" | "saving" | "unsaved" = status;
  let holdTimer: ReturnType<typeof setTimeout> | null = null;

  $: {
    if (status === "saved") {
      // Show "saved" immediately
      displayedStatus = "saved";
      // Hold it for 2s, ignoring "unsaved" during that window
      if (holdTimer) clearTimeout(holdTimer);
      holdTimer = setTimeout(() => {
        holdTimer = null;
      }, 2000);
    } else if (status === "saving") {
      displayedStatus = "saving";
    } else {
      // "unsaved" — only show if not in hold window
      if (!holdTimer) {
        displayedStatus = "unsaved";
      }
    }
  }

  onDestroy(() => {
    if (holdTimer) clearTimeout(holdTimer);
  });
</script>

<div class="flex items-center gap-2 text-sm" aria-live="polite" role="status">
  {#if displayedStatus === "saved"}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <IconCheck class="text-positive size-4" />
      <span class="text-positive">{m.flow_save_status_saved()}</span>
    </span>
  {:else if displayedStatus === "saving"}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <IconLoadingSpinner class="text-secondary size-4 animate-spin" />
      <span class="text-secondary">{m.flow_save_status_saving()}</span>
    </span>
  {:else}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <span class="text-warning-stronger font-medium">{m.flow_save_status_unsaved()}</span>
    </span>
  {/if}
</div>
