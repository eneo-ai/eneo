<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import UsageBadge from "./UsageBadge.svelte";

  export let requests: number;
</script>

<UsageBadge {requests} />
