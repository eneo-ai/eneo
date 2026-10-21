<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { ItemState, SourceState } from "$lib/features/integrations/sources";

  interface Props {
    state: SourceState | ItemState;
    class?: string;
  }

  let { state, class: className = "" }: Props = $props();

  const styles: Record<SourceState | ItemState, string> = {
    syncing: "bg-accent-dimmer text-accent-stronger",
    queued: "text-accent-stronger",
    attention: "bg-negative-dimmer text-negative-stronger",
    error: "bg-negative-dimmer text-negative-stronger",
    never: "text-secondary",
    empty: "bg-warning-dimmer text-warning-stronger",
    ok: "bg-positive-dimmer text-positive-stronger"
  };

  function label(value: SourceState | ItemState): string {
    switch (value) {
      case "syncing":
        return m.integration_source_state_syncing();
      case "queued":
        return m.integration_source_state_queued();
      case "attention":
        return m.integration_source_state_attention();
      case "error":
        return m.integration_sync_status_error();
      case "never":
        return m.integration_source_state_never();
      case "empty":
        return m.integration_sync_status_empty();
      case "ok":
        return m.integration_source_state_ok();
    }
  }
</script>

<Badge
  variant={state === "never" || state === "queued" ? "outline" : "secondary"}
  class="gap-1.5 {styles[state]} {className}"
>
  <span class="size-1.5 shrink-0 rounded-full bg-current" aria-hidden="true"></span>
  {label(state)}
</Badge>
