<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  One cell of the "Estimated cost" column. Splitting it out lets us wrap the
  string in a tooltip (svelte-headless-table cells must be strings or single
  components — there's no straightforward way to return a tooltip-wrapped
  string from `cell: (item) => ...`).
-->

<script lang="ts">
  import { Tooltip } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";

  export let label: string;
</script>

<Tooltip text={m.estimated_cost_tooltip()}>
  <span class="text-secondary tabular-nums">{label}</span>
</Tooltip>
