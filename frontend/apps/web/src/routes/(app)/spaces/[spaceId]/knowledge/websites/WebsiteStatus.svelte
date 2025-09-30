<script lang="ts">
  import type { WebsiteSparse } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  export let website: WebsiteSparse;

  function statusInfo(): { label: string; color: Label.LabelColor; tooltip?: string } {
    switch (website.latest_crawl?.status) {
      case "complete": {
        const completed = dayjs(website.latest_crawl?.finished_at);
        const label = `Synced ${dayjs().to(completed)}`;
        return {
          color: dayjs().diff(completed, "days") < 10 ? "green" : "yellow",
          label,
          tooltip: `Synced on ${completed.format("YYYY-MM-DD HH:mm")}`
        };
      }
      case "in progress": {
        const started = dayjs(website.latest_crawl?.created_at);
        const elapsed = dayjs().diff(started, 'minutes');
        return {
          color: "yellow",
          label: "Sync in progress",
          tooltip: `Started ${started.format("YYYY-MM-DD HH:mm")} (${elapsed} min ago)`
        };
      }
      case "failed":
        return {
          color: "orange",
          label: "Sync failed",
          tooltip: website.latest_crawl?.finished_at
            ? `Failed at ${dayjs(website.latest_crawl.finished_at).format("YYYY-MM-DD HH:mm")}`
            : undefined
        };
      case "not found":
        return {
          color: "orange",
          label: "Sync failed"
        };
      case "queued": {
        const queued = dayjs(website.latest_crawl?.created_at);
        return {
          color: "blue",
          label: "Queued",
          tooltip: `Queued at ${queued.format("YYYY-MM-DD HH:mm")}`
        };
      }
    }
    return {
      color: "orange",
      label: "error"
    };
  }

  $: status = statusInfo();
</script>

<Label.Single item={status}></Label.Single>
