<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { HelpCircle } from "lucide-svelte";

  let { text }: { text: string } = $props();
</script>

<Tooltip.Provider delayDuration={150}>
  <Tooltip.Root>
    <Tooltip.Trigger>
      {#snippet child({ props })}
        <button
          {...props}
          type="button"
          aria-label={text}
          class="text-muted/60 hover:text-muted hover:bg-surface-dimmer/80 focus-visible:text-accent-default focus-visible:bg-accent-dimmer/40 -mt-px inline-flex h-4 w-4 items-center justify-center rounded-full transition-colors duration-150 focus:outline-none"
        >
          <HelpCircle class="h-3.5 w-3.5" strokeWidth={2} />
        </button>
      {/snippet}
    </Tooltip.Trigger>
    <Tooltip.Content>{text}</Tooltip.Content>
  </Tooltip.Root>
</Tooltip.Provider>
