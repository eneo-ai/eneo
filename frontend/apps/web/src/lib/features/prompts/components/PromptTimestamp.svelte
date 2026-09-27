<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { formatTime } from "$lib/core/formatting/dateTime";
  import StatusBadge from "$lib/components/StatusBadge.svelte";

  import { m } from "$lib/paraglide/messages";

  export let prompt: {
    created_at?: string | null;
    description?: string | null;
    is_selected: boolean;
  };
</script>

<div class="flex items-center gap-4 px-3">
  <span>{formatTime(prompt.created_at)}</span>

  {#if prompt.is_selected}
    <StatusBadge item={{ label: m.latest(), color: "green" }} />
  {/if}
</div>
