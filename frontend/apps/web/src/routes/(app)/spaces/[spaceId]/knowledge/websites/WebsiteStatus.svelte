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

  type CrawlOutcome = {
    code: string;
    severity: "info" | "warning" | "error";
    message_key: string;
    detail?: string | null;
    affected_count?: number | null;
  };
  type WebsiteWithOutcome = WebsiteSparse & {
    latest_crawl?:
      | (NonNullable<WebsiteSparse["latest_crawl"]> & {
          outcome?: CrawlOutcome | null;
        })
      | null;
  };

  // eslint-disable-next-line svelte/no-immutable-reactive-statements
  $: dayjs.locale(getLocale());

  function latestOutcome(): CrawlOutcome | undefined {
    return (website as WebsiteWithOutcome).latest_crawl?.outcome ?? undefined;
  }

  function outcomeLabel(outcome: CrawlOutcome): string {
    const labels: Record<string, () => string> = {
      crawl_outcome_duplicate_skipped: () => m.crawl_outcome_duplicate_skipped(),
      crawl_outcome_embedding_config_missing: () => m.crawl_outcome_embedding_config_missing(),
      crawl_outcome_no_pages_returned: () => m.crawl_outcome_no_pages_returned(),
      crawl_outcome_timeout_no_pages: () => m.crawl_outcome_timeout_no_pages(),
      crawl_outcome_max_age_exceeded: () => m.crawl_outcome_max_age_exceeded(),
      crawl_outcome_source_retention_only: () => m.crawl_outcome_source_retention_only(),
      crawl_outcome_page_failures: () => m.crawl_outcome_page_failures(),
      crawl_outcome_unknown_error: () => m.crawl_outcome_unknown_error()
    };
    return labels[outcome.message_key]?.() ?? outcome.detail ?? m.sync_failed();
  }

  function outcomeTooltip(outcome: CrawlOutcome | undefined): string | undefined {
    if (!outcome) {
      return undefined;
    }

    const affected = outcome.affected_count
      ? `\n${m.crawl_outcome_affected_count({ count: outcome.affected_count })}`
      : "";
    const detail = outcome.detail ? `\n${outcome.detail}` : "";
    return `${outcomeLabel(outcome)}${affected}${detail}`;
  }

  function statusInfo(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const outcome = latestOutcome();
    const isDuplicateSkip = outcome?.code === "CRAWL_DUPLICATE_SKIPPED";
    const skipReason = website.latest_crawl?.result_location;
    const failureTooltip = outcomeTooltip(outcome) ?? skipReason ?? undefined;

    // Check if there are failures in the latest crawl
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
          label: outcome ? outcomeLabel(outcome) : m.sync_failed(),
          tooltip: failureTooltip
        };
      case "not found":
        return {
          color: "orange",
          label: outcome ? outcomeLabel(outcome) : m.sync_failed(),
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
