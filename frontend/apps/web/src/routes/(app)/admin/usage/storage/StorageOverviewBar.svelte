<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatPercent } from "$lib/core/formatting/formatPercent";
  import type { StorageUsageSummary } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    storageStats: StorageUsageSummary;
  };

  let { storageStats }: Props = $props();

  const totalAvailable = storageStats.limit;

  // For the colours we're currently just using names of css variables.
  const items = [
    {
      label: m.public_spaces(),
      size: storageStats.shared_used,
      colour: "chart-green"
    },
    {
      label: m.personal_spaces(),
      size: storageStats.personal_used,
      colour: "accent-default"
    },
    {
      label: m.free(),
      // There is an edge case where more space is used up than available,
      // in which case we want to show 0 instead of a negative number
      size: Math.max(totalAvailable - storageStats.total_used, 0),
      colour: "background-secondary"
    }
  ];
</script>

<Settings.Row
  title={m.storage_summary()}
  description={m.storage_summary_description()}
>
  <div class="flex flex-col gap-4">
    <div class="bg-secondary flex h-4 w-full overflow-clip rounded-full lg:mt-2">
      {#each items.filter((item) => item.size > 0) as item (item)}
        <div
          class="last-of-type:!border-none"
          style="width: {formatPercent(
            item.size / totalAvailable
          )}; min-width: 1.5%; background: var(--{item.colour}); border-right: 3px solid var(--background-primary)"
        ></div>
      {/each}
    </div>
    <div class="flex flex-wrap gap-x-6">
      <div>
        <span class="font-medium">{m.available()}</span>: {formatBytes(totalAvailable)}
      </div>
      {#each items as item (item)}
        <div class="flex items-center gap-2">
          <div
            style="background: var(--{item.colour})"
            class="border-stronger h-3 w-3 rounded-full border"
          ></div>
          <p>
            <span class="font-medium">{item.label}</span>: {formatBytes(item.size)}
            <span class="text-muted pl-2">({formatPercent(item.size / totalAvailable, 1)})</span>
          </p>
        </div>
      {/each}
    </div>
  </div>
</Settings.Row>
