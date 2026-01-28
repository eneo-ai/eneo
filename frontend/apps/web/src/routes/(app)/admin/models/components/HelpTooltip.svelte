<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Tooltip } from "@intric/ui";
  import { HelpCircle } from "lucide-svelte";

  export let text: string;
</script>

<Tooltip {text}>
  <button
    type="button"
    class="inline-flex items-center justify-center w-4 h-4 rounded-full -mt-px
      text-muted/60 hover:text-muted
      hover:bg-surface-dimmer/80
      transition-colors duration-150
      focus:outline-none focus-visible:text-accent-default focus-visible:bg-accent-dimmer/40"
    tabindex="-1"
  >
    <HelpCircle class="w-3.5 h-3.5" strokeWidth={2} />
  </button>
</Tooltip>
