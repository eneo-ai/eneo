<script lang="ts">
  import type { WebsiteSparse } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  import {
    getCrawlOutcomeLabel,
    getCrawlOutcomeTooltip,
    getLatestCrawlOutcome,
    isDuplicateCrawlSkip,
    isSourceRetentionOnly
  } from "$lib/features/knowledge/crawlOutcomePresentation";
  import "dayjs/locale/sv";
  import "dayjs/locale/en";
  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  export let website: WebsiteSparse;

  // eslint-disable-next-line svelte/no-immutable-reactive-statements
  $: dayjs.locale(getLocale());

  function completedTooltip(completed: dayjs.Dayjs, outcomeTooltip?: string): string {
    const syncedOn = m.synced_on({ date: completed.format("YYYY-MM-DD HH:mm") });
    return outcomeTooltip ? `${syncedOn}\n${outcomeTooltip}` : syncedOn;
  }

  function statusInfo(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const outcome = getLatestCrawlOutcome(website);
    const isDuplicateSkip = isDuplicateCrawlSkip(outcome);
    const skipReason = website.latest_crawl?.result_location;
    const failureTooltip =
      getCrawlOutcomeTooltip(outcome, m.sync_failed()) ?? skipReason ?? undefined;

    const pagesFailed = website.latest_crawl?.pages_failed ?? 0;
    const filesFailed = website.latest_crawl?.files_failed ?? 0;
    const hasFailures = pagesFailed > 0 || filesFailed > 0;

    if (website.latest_crawl?.status === "failed" && isDuplicateSkip) {
      return {
        color: "gray",
        label: m.sync_skipped(),
        tooltip: failureTooltip ?? m.crawl_skipped_duplicate()
      };
    }

    switch (website.latest_crawl?.status) {
      case "complete": {
        const completed = dayjs(website.latest_crawl?.finished_at);
        const label = m.synced_ago({ timeAgo: dayjs().to(completed) });
        const crawlOutcomeTooltip = getCrawlOutcomeTooltip(outcome, m.sync_failed());

        if (isSourceRetentionOnly(outcome)) {
          return {
            color: "green",
            label: getCrawlOutcomeLabel(outcome, label),
            tooltip: completedTooltip(completed, crawlOutcomeTooltip)
          };
        }

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
            tooltip: `${completedTooltip(completed, crawlOutcomeTooltip)} - ${failureText}`
          };
        }

        return {
          color: dayjs().diff(completed, "days") < 10 ? "green" : "yellow",
          label,
          tooltip: completedTooltip(completed, crawlOutcomeTooltip)
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
          label: outcome ? getCrawlOutcomeLabel(outcome, m.sync_failed()) : m.sync_failed(),
          tooltip: failureTooltip
        };
      case "not found":
        return {
          color: "orange",
          label: outcome ? getCrawlOutcomeLabel(outcome, m.sync_failed()) : m.sync_failed(),
          tooltip: failureTooltip
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
