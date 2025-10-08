<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { formatNumber } from "$lib/core/formatting/formatNumber";
  import { formatPercent } from "$lib/core/formatting/formatPercent";
  import { modelOrgs } from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import type { TokenUsageSummary } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    tokenStats: TokenUsageSummary;
  };

  let { tokenStats }: Props = $props();

  const items = $derived.by(() => {
    return Object.values(
      tokenStats.models.reduce(
        (acc, info) => {
          const org = info.model_org ?? "";
          if (!acc[org]) {
            acc[org] = {
              label: org || m.unknown_organization(),
              tokenCount: 0,
              colour: modelOrgs[org].chartColour,
              org: org
            };
          }
          acc[org].tokenCount += info.total_token_usage;
          return acc;
        },
        {} as Record<string, { label: string; tokenCount: number; colour: string; org: string }>
      )
    ).sort((a, b) => b.tokenCount - a.tokenCount);
  });
</script>

<Settings.Row
  title={m.token_summary()}
  description={m.token_summary_description()}
>
  <div class="flex flex-col gap-4">
    <div class="bg-secondary flex h-4 w-full overflow-clip rounded-full lg:mt-2">
      {#each items.filter((item) => item.tokenCount > 0) as item (item)}
        <div
          class="last-of-type:!border-none"
          style="width: {formatPercent(
            item.tokenCount / tokenStats.total_token_usage
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
              item.tokenCount,
              "compact"
            )}
          </p>
        </div>
      {/each}
    </div>
  </div>
</Settings.Row>
