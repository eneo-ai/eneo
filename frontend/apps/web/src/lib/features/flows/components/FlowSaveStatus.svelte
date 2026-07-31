<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import CheckCircle2 from "lucide-svelte/icons/check-circle-2";
  import Loader2 from "lucide-svelte/icons/loader-2";
  import Circle from "lucide-svelte/icons/circle";
  import { fade } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";

  let {
    status
  }: {
    status: "saved" | "saving" | "unsaved";
  } = $props();
</script>

<div aria-live="polite" role="status">
  {#if status === "saved"}
    <span class="flex items-center gap-1.5" in:fade={{ duration: 150 }}>
      <Badge variant="outline" class="border-default/60 text-muted-foreground gap-1.5">
        <CheckCircle2 class="size-3" />
        {m.flow_save_status_saved()}
      </Badge>
    </span>
  {:else if status === "saving"}
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
