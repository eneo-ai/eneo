<script lang="ts">
  import type { WebsiteSparse } from "@eneo/eneo-js";
  import { Label } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  import "dayjs/locale/sv";
  import "dayjs/locale/en";
  import {
    crawlRunFailureMessage,
    crawlRunState,
    crawlRunStateLabel
  } from "$lib/features/knowledge/crawlRunState";
  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  export let website: WebsiteSparse;

  // Set dayjs locale based on paraglide locale
  // eslint-disable-next-line svelte/no-immutable-reactive-statements
  $: dayjs.locale(getLocale());
  /* TODO colours */
  function statusInfo(): { label: string; color: Label.LabelColor; tooltip?: string } {
    const crawl = website.latest_crawl;
    if (!crawl) {
      return {
        color: "gray",
        label: m.not_synced()
      };
    }

    const state = crawlRunState(crawl);
    const stateLabel = crawlRunStateLabel(state);

    const pagesFailed = crawl.pages_failed ?? 0;
    const filesFailed = crawl.files_failed ?? 0;
    const hasFailures = pagesFailed > 0 || filesFailed > 0;

    switch (state) {
      case "succeeded":
      case "partial": {
        const completed = dayjs(crawl.finished_at);
        const label = m.synced_ago({ timeAgo: dayjs().to(completed) });

        if (state === "partial" || hasFailures) {
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
            label: stateLabel,
            tooltip: `${m.synced_on({ date: completed.format("YYYY-MM-DD HH:mm") })} - ${failureText}`
          };
        }

        return {
          color: dayjs().diff(completed, "days") < 10 ? "green" : "yellow",
          label,
          tooltip: m.synced_on({ date: completed.format("YYYY-MM-DD HH:mm") })
        };
      }
      case "unchanged":
        return {
          color: "green",
          label: stateLabel,
          tooltip: m.synced_on({
            date: dayjs(crawl.finished_at).format("YYYY-MM-DD HH:mm")
          })
        };
      case "empty":
        return {
          color: "yellow",
          label: stateLabel
        };
      case "queued":
        return {
          color: "blue",
          label: stateLabel,
          tooltip: m.started_on({ date: dayjs(crawl.created_at).format("YYYY-MM-DD HH:mm") })
        };
      case "running":
      case "finalizing":
      case "stopping":
        return {
          color: "yellow",
          label: stateLabel,
          tooltip: m.started_on({ date: dayjs(crawl.created_at).format("YYYY-MM-DD HH:mm") })
        };
      case "cancelled":
        return {
          color: "gray",
          label: stateLabel,
          tooltip: crawlRunFailureMessage(crawl)
        };
      case "failed":
      case "interrupted":
        return {
          color: "orange",
          label: stateLabel,
          tooltip: crawlRunFailureMessage(crawl)
        };
      case "unknown":
        return {
          color: "orange",
          label: stateLabel,
          tooltip: m.crawl_failure_unknown()
        };
    }
  }
</script>

<Label.Single item={statusInfo()}></Label.Single>
