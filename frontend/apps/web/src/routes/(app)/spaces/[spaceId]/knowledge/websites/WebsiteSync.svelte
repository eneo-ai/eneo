<script lang="ts">
  import type { WebsiteSparse } from "@intric/intric-js";
  import { Label } from "@intric/ui";

  export let updateInterval: WebsiteSparse["update_interval"];

  // Reactive statement to get the interval info with fallback
  $: intervalItem = (() => {
    const key = updateInterval ?? "error";
    const item = intervalInfo[key];

    if (!item) {
      return intervalInfo.error;
    }

    return item;
  })();
  const intervalInfo: Record<string, { label: string; color: Label.LabelColor; tooltip: string }> =
    {
      daily: {
        color: "green",
        label: "Daily",
        tooltip: "Updates every day at 2 AM Sweden time"
      },
      every_other_day: {
        color: "green",
        label: "Every other day",
        tooltip: "Updates every other day at 2 AM Sweden time"
      },
      weekly: {
        color: "green",
        label: "Weekly",
        tooltip: "Updates every Friday at 11 PM Sweden time"
      },
      never: {
        color: "gray",
        label: "Never",
        tooltip: "No automatic updates - manual sync only"
      },
      // Legacy intervals (for backward compatibility)
      every_3_days: {
        color: "green",
        label: "Every other day",
        tooltip: "Updates every other day at 2 AM Sweden time (migrated from every 3 days)"
      },
      every_2_weeks: {
        color: "green",
        label: "Weekly",
        tooltip: "Updates every Friday at 11 PM Sweden time (migrated from every 2 weeks)"
      },
      monthly: {
        color: "green",
        label: "Weekly",
        tooltip: "Updates every Friday at 11 PM Sweden time (migrated from monthly)"
      },
      error: {
        color: "orange",
        label: "Unknown interval",
        tooltip: "Unknown update interval - please edit website settings"
      }
    };
</script>

<Label.Single item={intervalItem}></Label.Single>
