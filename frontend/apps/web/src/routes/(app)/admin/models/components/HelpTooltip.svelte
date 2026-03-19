<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Tooltip } from "@intric/ui";
  import { HelpCircle } from "lucide-svelte";

  export let text: string;
</script>

<Tooltip {text}>
  <button
    type="button"
    class="text-muted/60 hover:text-muted hover:bg-surface-dimmer/80 focus-visible:text-accent-default focus-visible:bg-accent-dimmer/40 -mt-px inline-flex
      h-4 w-4
      items-center
      justify-center rounded-full
      transition-colors duration-150 focus:outline-none"
    tabindex="-1"
  >
    <HelpCircle class="h-3.5 w-3.5" strokeWidth={2} />
  </button>
</Tooltip>
