<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import UsageBadge from "./UsageBadge.svelte";

  export let tokens: number;
  export let highThreshold: number = 500_000;
  export let mediumThreshold: number = 50_000;
</script>

<UsageBadge {tokens} {highThreshold} {mediumThreshold} />
