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
  const SKIPPED_PREFIX = "skipped duplicate crawl";

  // Set dayjs locale based on paraglide locale
  $: dayjs.locale(getLocale());
  /* TODO colours */
  function statusInfo(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const skipReason = website.latest_crawl?.result_location;
    const skipTooltip = skipReason?.toLowerCase().startsWith(SKIPPED_PREFIX)
      ? m.crawl_skipped_duplicate()
      : skipReason;

    if (
      website.latest_crawl?.status === "failed" &&
      skipReason?.toLowerCase().startsWith(SKIPPED_PREFIX)
    ) {
      return {
        color: "gray",
        label: m.sync_skipped(),
        tooltip: skipTooltip
      };
    }

    switch (website.latest_crawl?.status) {
      case "complete": {
        const completed = dayjs(website.latest_crawl?.finished_at);
        const label = m.synced_ago({ timeAgo: dayjs().to(completed) });
        return {
          color: dayjs().diff(completed, "days") < 10 ? "green" : "yellow",
          label,
          tooltip: m.synced_on({ date: completed.format("YYYY-MM-DD HH:mm") })
        };
      }
      case "in progress":
        return {
          color: "yellow",
          label: m.sync_in_progress(),
          tooltip: m.started_on({
            date: dayjs(website.latest_crawl?.created_at).format("YYYY-MM-DD HH:mm")
          })
        };
      case "failed":
        return {
          color: "orange",
          label: m.sync_failed(),
          tooltip: skipTooltip
        };
      case "not found":
        return {
          color: "orange",
          label: m.sync_failed(),
          tooltip: skipTooltip
        };
      case "queued":
        return {
          color: "blue",
          label: m.queued()
        };
    }
    return {
      color: "orange",
      label: "error"
    };
  }
</script>

<Label.Single item={statusInfo()}></Label.Single>
