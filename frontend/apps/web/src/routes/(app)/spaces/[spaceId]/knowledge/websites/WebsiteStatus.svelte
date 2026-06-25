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
  type WebsiteIntegrationStatus = {
    webhook_status: string;
    last_successful_sync_at?: string | null;
    last_sync_error?: string | null;
  };

  // Set dayjs locale based on paraglide locale
  // eslint-disable-next-line svelte/no-immutable-reactive-statements
  $: dayjs.locale(getLocale());
  /* TODO colours */
  function statusInfo(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const integration = (
      website as WebsiteSparse & { integration?: WebsiteIntegrationStatus | null }
    ).integration;
    if (integration?.webhook_status === "queued") {
      return {
        color: "blue",
        label: m.queued(),
        tooltip: m.website_sync_waiting()
      };
    }
    if (integration?.webhook_status === "in_progress") {
      return {
        color: "yellow",
        label: m.sync_in_progress(),
        tooltip: m.website_sync_fetching()
      };
    }
    if (integration?.webhook_status === "failed") {
      return {
        color: "orange",
        label: m.sync_failed(),
        tooltip: integration.last_sync_error ?? m.website_sync_failed_latest()
      };
    }
    if (integration?.webhook_status === "complete" && integration?.last_successful_sync_at) {
      const completed = dayjs(integration.last_successful_sync_at);
      return {
        color: dayjs().diff(completed, "days") < 10 ? "green" : "yellow",
        label: m.synced_ago({ timeAgo: dayjs().to(completed) }),
        tooltip: m.sitemap_synced_on({ date: completed.format("YYYY-MM-DD HH:mm") })
      };
    }

    const skipReason = website.latest_crawl?.result_location;
    const skipTooltip: string | undefined = skipReason?.toLowerCase().startsWith(SKIPPED_PREFIX)
      ? m.crawl_skipped_duplicate()
      : (skipReason ?? undefined);

    // Check if there are failures in the latest crawl
    const pagesFailed = website.latest_crawl?.pages_failed ?? 0;
    const filesFailed = website.latest_crawl?.files_failed ?? 0;
    const hasFailures = pagesFailed > 0 || filesFailed > 0;

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

        // If there are failures, show warning color and include failure info in tooltip
        if (hasFailures) {
          let failureText: string;
          if (pagesFailed > 0 && filesFailed > 0) {
            failureText = m.pages_and_files_failed({
              pages: pagesFailed.toString(),
              files: filesFailed.toString()
            });
          } else if (pagesFailed > 0) {
            failureText = m.pages_failed({ count: pagesFailed.toString() });
          } else {
            failureText = m.files_failed({ count: filesFailed.toString() });
          }

          return {
            color: "yellow",
            label: m.synced_with_warnings(),
            tooltip: `${m.synced_on({ date: completed.format("YYYY-MM-DD HH:mm") })} - ${failureText}`
          };
        }

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
      label: m.error()
    };
  }
</script>

<Label.Single item={statusInfo()}></Label.Single>
