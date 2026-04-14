<script lang="ts">
  import { getStatusTooltip, getStateStyle } from "$lib/features/api-keys/apiKeyTableUtils";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";

  let { state } = $props<{ state: string }>();

  const style = $derived(getStateStyle(state));
</script>

<Tooltip.Provider delayDuration={150}>
  <Tooltip.Root>
    <Tooltip.Trigger>
      {#snippet child({ props })}
        <span {...props} class="flex items-center gap-1.5">
          <span class="h-2.5 w-2.5 rounded-full {style.dotClasses}" aria-hidden="true"></span>
          <span class="text-muted text-xs">{style.label}</span>
          <span class="sr-only">{getStatusTooltip(state)}</span>
        </span>
      {/snippet}
    </Tooltip.Trigger>
    <Tooltip.Content>
      {getStatusTooltip(state)}
    </Tooltip.Content>
  </Tooltip.Root>
</Tooltip.Provider>
