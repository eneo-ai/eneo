<script lang="ts">
  import type { WebsiteSparse } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import dayjs from "dayjs";
  import relativeTime from "dayjs/plugin/relativeTime";
  import utc from "dayjs/plugin/utc";
  dayjs.extend(relativeTime);
  dayjs.extend(utc);

  export let website: WebsiteSparse;

  // Reactive statement to update status when website changes
  $: statusData = (() => {
    try {
      return statusInfo();
    } catch (error) {
      console.error('Error in statusInfo:', error);
      return {
        color: "gray" as Label.LabelColor,
        label: "Error",
        tooltip: "Unable to determine website status. Please refresh the page."
      };
    }
  })();
  function statusInfo(): { label: string; color: Label.LabelColor; tooltip: string } {
    // Safety check to ensure website is defined
    if (!website) {
      return {
        color: "gray",
        label: "Loading...",
        tooltip: "Loading website information..."
      };
    }

    const crawl = website.latest_crawl;

    // Handle case where no crawls have been run yet
    if (!crawl) {
      return {
        color: "gray",
        label: "Never synced",
        tooltip: "This website has not been crawled yet. Click 'Sync now' to start the first crawl."
      };
    }

    switch (crawl.status) {
      case "complete": {
        try {
          const completed = dayjs(crawl.finished_at);
          const daysAgo = dayjs().diff(completed, "days");

          // More descriptive success states based on recency
          let color: Label.LabelColor = "green";
          if (daysAgo > 30) {
            color = "orange";
          } else if (daysAgo > 10) {
            color = "yellow";
          }

          const label = `Synced ${dayjs().to(completed)}`;
          const pagesInfo = crawl.pages_crawled ? ` (${crawl.pages_crawled} pages` : "";
          const filesInfo = crawl.files_downloaded ? `, ${crawl.files_downloaded} files)` : pagesInfo ? ")" : "";

          return {
            color,
            label,
            tooltip: `Last sync: ${completed.format("YYYY-MM-DD HH:mm")}${pagesInfo}${filesInfo}`
          };
        } catch (error) {
          return {
            color: "green",
            label: "Sync completed",
            tooltip: "Crawl completed successfully (unable to parse completion date)"
          };
        }
      }

      case "in progress": {
        try {
          const started = dayjs(crawl.created_at);
          const duration = dayjs().diff(started, "minutes");

          return {
            color: "blue",
            label: `Syncing... (${duration}m)`,
            tooltip: `Crawl started ${started.format("YYYY-MM-DD HH:mm")}. This may take several minutes depending on website size.`
          };
        } catch (error) {
          return {
            color: "blue",
            label: "Syncing...",
            tooltip: "Crawl is currently in progress. This may take several minutes depending on website size."
          };
        }
      }

      case "failed": {
        try {
          const failed = dayjs(crawl.finished_at || crawl.created_at);
          const pagesInfo = crawl.pages_crawled ? ` ${crawl.pages_crawled} pages processed before failure.` : "";

          return {
            color: "red",
            label: "Sync failed",
            tooltip: `Last attempt failed on ${failed.format("YYYY-MM-DD HH:mm")}.${pagesInfo} Check website accessibility, authentication, or network connectivity.`
          };
        } catch (error) {
          return {
            color: "red",
            label: "Sync failed",
            tooltip: "Last crawl attempt failed. Check website accessibility, authentication, or network connectivity."
          };
        }
      }

      case "not found": {
        try {
          const failed = dayjs(crawl.finished_at || crawl.created_at);

          return {
            color: "red",
            label: "Website not found",
            tooltip: `Website could not be found on ${failed.format("YYYY-MM-DD HH:mm")}. Check if the URL is correct and accessible.`
          };
        } catch (error) {
          return {
            color: "red",
            label: "Website not found",
            tooltip: "Website could not be found. Check if the URL is correct and accessible."
          };
        }
      }

      case "queued": {
        try {
          const queued = dayjs(crawl.created_at);
          const waitTime = dayjs().diff(queued, "minutes");

          return {
            color: "blue",
            label: waitTime > 5 ? `Queued (${waitTime}m)` : "Queued",
            tooltip: `Crawl queued ${queued.format("HH:mm")}. Your website will be processed shortly by our crawl workers.`
          };
        } catch (error) {
          return {
            color: "blue",
            label: "Queued",
            tooltip: "Crawl is queued and will be processed shortly by our crawl workers."
          };
        }
      }

      default: {
        return {
          color: "gray",
          label: "Unknown status",
          tooltip: "Unable to determine crawl status. Please try refreshing the page."
        };
      }
    }
  }
</script>

<Label.Single item={statusData}></Label.Single>
