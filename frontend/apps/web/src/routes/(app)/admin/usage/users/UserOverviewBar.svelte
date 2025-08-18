<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { formatNumber } from "$lib/core/formatting/formatNumber";
  import { formatPercent } from "$lib/core/formatting/formatPercent";
  import type { UserTokenUsageSummary } from "@intric/intric-js";

  type Props = {
    userStats: UserTokenUsageSummary;
  };

  let { userStats }: Props = $props();

  const items = $derived.by(() => {
    // Group users by usage level (High, Medium, Low) for the visual bar
    const high = userStats.users.filter(user => user.total_requests > 100);
    const medium = userStats.users.filter(user => user.total_requests > 20 && user.total_requests <= 100);
    const low = userStats.users.filter(user => user.total_requests <= 20);

    return [
      {
        label: "High Usage Users",
        userCount: high.length,
        tokenCount: high.reduce((sum, user) => sum + user.total_tokens, 0),
        colour: "chart-red"
      },
      {
        label: "Medium Usage Users",
        userCount: medium.length,
        tokenCount: medium.reduce((sum, user) => sum + user.total_tokens, 0),
        colour: "chart-yellow"
      },
      {
        label: "Low Usage Users",
        userCount: low.length,
        tokenCount: low.reduce((sum, user) => sum + user.total_tokens, 0),
        colour: "chart-green"
      }
    ].filter(item => item.userCount > 0).sort((a, b) => b.tokenCount - a.tokenCount);
  });
</script>

<Settings.Row
  title="User summary"
  description="See how many tokens your organization's users have been consuming broken down by usage level."
>
  <div class="flex flex-col gap-4">
    <div class="bg-secondary flex h-4 w-full overflow-clip rounded-full lg:mt-2">
      {#each items.filter((item) => item.tokenCount > 0) as item (item)}
        <div
          class="last-of-type:!border-none"
          style="width: {formatPercent(
            item.tokenCount / userStats.total_tokens
          )}; min-width: 1.5%; background: var(--{item.colour}); border-right: 3px solid var(--background-primary)"
        ></div>
      {/each}
    </div>
    <div class="flex flex-wrap gap-x-6">
      {#each items as item (item)}
        <div class="flex items-center gap-2">
          <div
            style="background: var(--{item.colour})"
            class="border-stronger h-3 w-3 rounded-full border"
          ></div>
          <p>
            <span class="font-medium">{item.label}</span>: {formatNumber(
              item.userCount
            )} users, {formatNumber(item.tokenCount, "compact")} tokens
          </p>
        </div>
      {/each}
    </div>
  </div>
</Settings.Row>
