<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { CrawlerActiveInventoryResponse } from "$lib/features/admin/crawlerActiveInventory";
  import type { CrawlerTenantFailureInventoryResponse } from "$lib/features/admin/crawlerFailureInventory";
  import type { CrawlerScheduledAggregateResponse } from "$lib/features/admin/crawlerScheduledAggregate";

  type CrawlerAdminTab = "operations" | "websites" | "health" | "activity" | "settings";

  type Props = {
    visibleActiveInventory: CrawlerActiveInventoryResponse | null;
    failureInventory: CrawlerTenantFailureInventoryResponse | null;
    scheduledAggregate: CrawlerScheduledAggregateResponse | null;
    currentTab: CrawlerAdminTab;
    onSelectTab: (tab: CrawlerAdminTab) => void;
  };

  const {
    visibleActiveInventory,
    failureInventory,
    scheduledAggregate,
    currentTab,
    onSelectTab
  }: Props = $props();

  // Warning tint only applies to the failing-count card when the
  // count is non-zero, so a healthy fleet doesn't show alarming
  // styling. Neutral resting otherwise.
  function kpiButtonClass(pressed: boolean, tone: "neutral" | "warning" = "neutral"): string {
    const base =
      "focus-visible:ring-ring/50 flex flex-col items-start gap-1.5 rounded-lg border p-4 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none";
    const pressedStyle =
      tone === "warning"
        ? "border-caution/50 bg-caution/8 ring-caution/30 ring-1"
        : "border-accent-default/50 bg-accent-default/8 ring-accent-default/30 ring-1";
    const restingStyle = "border-border bg-background hover:bg-muted";
    return `${base} ${pressed ? pressedStyle : restingStyle}`;
  }
</script>

<div
  class="mb-8 grid grid-cols-1 gap-3 sm:grid-cols-3"
  role="group"
  aria-label={m.crawler_summary_aria()}
>
  <button
    type="button"
    class={kpiButtonClass(currentTab === "operations")}
    aria-pressed={currentTab === "operations"}
    onclick={() => onSelectTab("operations")}
  >
    <span class="text-muted-foreground text-xs tracking-wide uppercase">
      {m.crawler_summary_running_label()}
    </span>
    <span class="text-3xl leading-none font-semibold tabular-nums">
      {visibleActiveInventory ? visibleActiveInventory.total : 0}
    </span>
    <span class="text-muted-foreground text-xs">
      {m.crawler_summary_running_hint()}
    </span>
  </button>
  <button
    type="button"
    class={kpiButtonClass(
      currentTab === "health",
      (failureInventory?.total ?? 0) > 0 ? "warning" : "neutral"
    )}
    aria-pressed={currentTab === "health"}
    onclick={() => onSelectTab("health")}
  >
    <span class="text-muted-foreground text-xs tracking-wide uppercase">
      {m.crawler_summary_failing_label()}
    </span>
    <span
      class="text-3xl leading-none font-semibold tabular-nums {(failureInventory?.total ?? 0) > 0
        ? 'text-caution'
        : ''}"
    >
      {failureInventory ? failureInventory.total : 0}
    </span>
    <span class="text-muted-foreground text-xs">
      {m.crawler_summary_failing_hint()}
    </span>
  </button>
  <button
    type="button"
    class={kpiButtonClass(currentTab === "activity")}
    aria-pressed={currentTab === "activity"}
    onclick={() => onSelectTab("activity")}
  >
    <span class="text-muted-foreground text-xs tracking-wide uppercase">
      {m.crawler_summary_scheduled_label()}
    </span>
    <span class="text-3xl leading-none font-semibold tabular-nums">
      {scheduledAggregate ? scheduledAggregate.total_websites : 0}
    </span>
    <span class="text-muted-foreground text-xs">
      {m.crawler_summary_scheduled_hint()}
    </span>
  </button>
</div>
