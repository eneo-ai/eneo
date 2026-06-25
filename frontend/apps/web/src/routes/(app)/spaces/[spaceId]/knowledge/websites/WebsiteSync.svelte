<script lang="ts">
  import type { WebsiteSparse } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  import "dayjs/locale/sv";
  import "dayjs/locale/en";

  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  export let website: WebsiteSparse;
  type WebsiteIntegrationMeta = {
    webhook_status?: string;
    last_successful_sync_at?: string | null;
  };

  // Set dayjs locale based on paraglide locale
  // eslint-disable-next-line svelte/no-immutable-reactive-statements
  $: dayjs.locale(getLocale());

  const intervalLabels: Record<string, { label: string; color: Label.LabelColor }> = {
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

  function integrationItem(): { label: string; color: Label.LabelColor; tooltip?: string } | null {
    const integration = (website as WebsiteSparse & { integration?: WebsiteIntegrationMeta | null })
      .integration;
    if (!integration) {
      return null;
    }

    return {
      color: "blue",
      label: m.updates_on_changes(),
      tooltip: integration.last_successful_sync_at
        ? m.integration_auto_updates_tooltip_with_date({
            date: dayjs(integration.last_successful_sync_at).format("YYYY-MM-DD HH:mm")
          })
        : m.integration_auto_updates_tooltip()
    };
  }

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

    const nextAt = dayjs(lastCrawlAt).add(days, "day");
    const relative = dayjs().to(nextAt);
    const formatted = `${nextAt.format("YYYY-MM-DD HH:mm")} (${relative})`;
    return m.next_crawl_on({ date: formatted });
  }

  $: intervalKey = website.update_interval ?? "error";
  $: intervalLabel = intervalLabels[intervalKey] ?? intervalLabels.error;
  $: intervalItem = integrationItem() ?? {
    ...intervalLabel,
    tooltip: nextCrawlTooltip(intervalKey)
  };
</script>

<Label.Single item={intervalItem}></Label.Single>
