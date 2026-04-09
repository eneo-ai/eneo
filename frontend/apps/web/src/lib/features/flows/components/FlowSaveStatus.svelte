<script lang="ts">
  import { Badge } from "@eneo/ui";
  import { CheckCircle2, Loader2, Circle } from "lucide-svelte";
  import { fade } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
  import { onDestroy } from "svelte";

  export let status: "saved" | "saving" | "unsaved";

  let displayedStatus: "saved" | "saving" | "unsaved" = status;
  let holdTimer: ReturnType<typeof setTimeout> | null = null;

  $: {
    if (status === "saved") {
      displayedStatus = "saved";
      if (holdTimer) clearTimeout(holdTimer);
      holdTimer = setTimeout(() => {
        holdTimer = null;
      }, 2000);
    } else if (status === "saving") {
      displayedStatus = "saving";
    } else {
      if (!holdTimer) {
        displayedStatus = "unsaved";
      }
    }
  }

  onDestroy(() => {
    if (holdTimer) clearTimeout(holdTimer);
  });
</script>

<div aria-live="polite" role="status">
  {#if displayedStatus === "saved"}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <Badge variant="outline" class="gap-1.5 border-default/60 text-muted-foreground">
        <CheckCircle2 class="size-3" />
        {m.flow_save_status_saved()}
      </Badge>
    </span>
  {:else if displayedStatus === "saving"}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <Badge variant="outline" class="gap-1.5 border-default bg-secondary/50 text-secondary">
        <Loader2 class="size-3 animate-spin" />
        {m.flow_save_status_saving()}
      </Badge>
    </span>
  {:else}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <Badge variant="outline" class="gap-1.5 border-warning-default/20 bg-warning-dimmer/50 text-warning-stronger font-medium">
        <Circle class="size-2.5 fill-current" />
        {m.flow_save_status_unsaved()}
      </Badge>
    </span>
  {/if}
</div>
