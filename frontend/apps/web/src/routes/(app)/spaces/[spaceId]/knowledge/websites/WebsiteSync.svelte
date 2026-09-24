<script lang="ts">
  import { formatDateTime, formatRelativeTime, DAY_MS } from "$lib/core/formatting/dateTime";
  import type { WebsiteSparse } from "@eneo/eneo-js";
  import StatusBadge, { type StatusBadgeColor } from "$lib/components/StatusBadge.svelte";
  import { m } from "$lib/paraglide/messages";

  export let website: WebsiteSparse;

  // eslint-disable-next-line svelte/no-immutable-reactive-statements

  const intervalLabels: Record<string, { label: string; color: StatusBadgeColor }> = {
    daily: {
      color: "green",
      label: m.every_day()
    },
    every_other_day: {
      color: "green",
      label: m.every_other_day()
    },
    weekly: {
      color: "green",
      label: m.weekly()
    },
    never: {
      color: "gray",
      label: m.never()
    },
    error: {
      color: "orange",
      label: m.not_found()
    }
  };

  const intervalDays: Record<string, number> = {
    daily: 1,
    every_other_day: 2,
    weekly: 7
  };

  function nextCrawlTooltip(intervalKey: string): string | undefined {
    if (intervalKey === "never") {
      return undefined;
    }

    const days = intervalDays[intervalKey];
    if (!days) {
      return undefined;
    }

    const lastCrawlAt = website.latest_crawl?.finished_at ?? website.latest_crawl?.created_at;
    if (!lastCrawlAt) {
      return m.next_crawl_after_first_run();
    }

    const nextAt = new Date(lastCrawlAt).getTime() + days * DAY_MS;
    const formatted = `${formatDateTime(nextAt)} (${formatRelativeTime(nextAt)})`;
    return m.next_crawl_on({ date: formatted });
  }

  $: intervalKey = website.update_interval ?? "error";
  $: intervalLabel = intervalLabels[intervalKey] ?? intervalLabels.error;
  $: intervalItem = {
    ...intervalLabel,
    tooltip: nextCrawlTooltip(intervalKey)
  };
</script>

<StatusBadge item={intervalItem} />
