<script lang="ts">
  import { untrack } from "svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { CheckCircle2, Loader2, Circle } from "lucide-svelte";
  import { fade } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";

  let {
    status
  }: {
    status: "saved" | "saving" | "unsaved";
  } = $props();

  let displayedStatus: "saved" | "saving" | "unsaved" = $state(untrack(() => status));
  let holdTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    // Only react to `status` changes — untrack holdTimer reads to avoid cycles
    if (status === "saved") {
      displayedStatus = "saved";
      untrack(() => {
        if (holdTimer) clearTimeout(holdTimer);
        holdTimer = setTimeout(() => {
          holdTimer = null;
          displayedStatus = "unsaved";
        }, 2000);
      });
    } else if (status === "saving") {
      displayedStatus = "saving";
    } else {
      untrack(() => {
        if (!holdTimer) {
          displayedStatus = "unsaved";
        }
      });
    }

    return () => {
      if (holdTimer) clearTimeout(holdTimer);
    };
  });
</script>

<div aria-live="polite" role="status">
  {#if displayedStatus === "saved"}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <Badge variant="outline" class="border-default/60 text-muted-foreground gap-1.5">
        <CheckCircle2 class="size-3" />
        {m.flow_save_status_saved()}
      </Badge>
    </span>
  {:else if displayedStatus === "saving"}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <Badge variant="outline" class="border-default bg-secondary/50 text-secondary gap-1.5">
        <Loader2 class="size-3 animate-spin" />
        {m.flow_save_status_saving()}
      </Badge>
    </span>
  {:else}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <Badge
        variant="outline"
        class="border-warning-default/20 bg-warning-dimmer/50 text-warning-stronger gap-1.5 font-medium"
      >
        <Circle class="size-2.5 fill-current" />
        {m.flow_save_status_unsaved()}
      </Badge>
    </span>
  {/if}
</div>
