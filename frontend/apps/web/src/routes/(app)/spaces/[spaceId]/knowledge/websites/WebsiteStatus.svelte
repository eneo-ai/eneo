<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { WebsiteSparse } from "@intric/intric-js";
  import StatusBadge, { type StatusTone } from "$lib/components/StatusBadge.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  import {
    getCrawlOutcomeLabel,
    getCrawlOutcomeTooltip,
    getCrawlRunFailureTooltip,
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

  function statusInfo(website: WebsiteSparse): {
    label: string;
    tone: StatusTone;
    tooltip?: string;
  } {
    const outcome = getLatestCrawlOutcome(website);
    const isDuplicateSkip = isDuplicateCrawlSkip(outcome);
    const failureTooltip = website.latest_crawl
      ? getCrawlRunFailureTooltip(website.latest_crawl, m.sync_failed())
      : undefined;

    const pagesFailed = website.latest_crawl?.pages_failed ?? 0;
    const filesFailed = website.latest_crawl?.files_failed ?? 0;
    const hasFailures = pagesFailed > 0 || filesFailed > 0;

    if (website.latest_crawl?.status === "failed" && isDuplicateSkip) {
      return {
        tone: "neutral",
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
            tone: "positive",
            label: getCrawlOutcomeLabel(outcome, label),
            tooltip: completedTooltip(completed, crawlOutcomeTooltip)
          };
        }

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
            tone: "warning",
            label: m.synced_with_warnings(),
            tooltip: `${completedTooltip(completed, crawlOutcomeTooltip)} - ${failureText}`
          };
        }

        return {
          tone: dayjs().diff(completed, "days") < 10 ? "positive" : "warning",
          label,
          tooltip: completedTooltip(completed, crawlOutcomeTooltip)
        };
      }
      case "in progress":
        return {
          tone: "warning",
          label: m.sync_in_progress(),
          tooltip: m.started_on({
            date: dayjs(website.latest_crawl?.created_at).format("YYYY-MM-DD HH:mm")
          })
        };
      case "failed":
      case "not found":
        return {
          tone: "negative",
          label: outcome ? getCrawlOutcomeLabel(outcome, m.sync_failed()) : m.sync_failed(),
          tooltip: failureTooltip
        };
      case "queued":
        return {
          tone: "info",
          label: m.queued()
        };
    }
    return {
      tone: "negative",
      label: "error"
    };
  }

  $: status = statusInfo(website);
</script>

<StatusBadge tone={status.tone} tooltip={status.tooltip}>
  {status.label}
</StatusBadge>
