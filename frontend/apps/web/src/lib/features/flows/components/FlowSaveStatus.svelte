<script lang="ts">
  import { IconCheck } from "@intric/icons/check";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { fade } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";

  export let status: "saved" | "saving" | "unsaved";
</script>

<div class="flex items-center gap-1.5 text-xs" aria-live="polite" role="status">
  {#key status}
    <span class="flex items-center gap-1.5" transition:fade={{ duration: 150 }}>
      {#if status === "saved"}
        <IconCheck class="text-positive size-3.5" />
        <span class="text-positive">{m.flow_save_status_saved()}</span>
      {:else if status === "saving"}
        <IconLoadingSpinner class="text-secondary size-3.5 animate-spin" />
        <span class="text-secondary">{m.flow_save_status_saving()}</span>
      {:else}
        <span class="text-warning-stronger font-medium">{m.flow_save_status_unsaved()}</span>
      {/if}
    </span>
  {/key}
</div>
