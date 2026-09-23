<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  One cell of the "Estimated cost" column. Splitting it out lets us wrap the
  string in a tooltip (a table cell renders a string or a single component).
-->

<script lang="ts">
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";

  export let label: string;
</script>

<Tooltip.Root>
  <Tooltip.Trigger>
    {#snippet child({ props })}
      <span {...props} class="text-secondary tabular-nums">{label}</span>
    {/snippet}
  </Tooltip.Trigger>
  <Tooltip.Content>{m.estimated_cost_tooltip()}</Tooltip.Content>
</Tooltip.Root>
