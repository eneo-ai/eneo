<script lang="ts">
  import type { WebsiteSparse } from "@intric/intric-js";
  import { Label } from "@intric/ui";

  export let updateInterval: WebsiteSparse["update_interval"];
  /* TODO colours */
  const intervalInfo: Record<string, { label: string; color: Label.LabelColor; tooltip?: string }> =
    {
      daily: {
        color: "green",
        label: "Daily",
        tooltip: "Updates every day at 2 AM"
      },
      every_3_days: {
        color: "green",
        label: "Every 3 days",
        tooltip: "Updates every 3 days at 2 AM"
      },
      weekly: {
        color: "green",
        label: "Weekly",
        tooltip: "Updates every Friday at 11 PM"
      },
      every_2_weeks: {
        color: "green",
        label: "Every 2 weeks",
        tooltip: "Updates every 2 weeks on Friday at 11 PM"
      },
      monthly: {
        color: "green",
        label: "Monthly",
        tooltip: "Updates on the 1st of each month at 2 AM"
      },
      never: {
        color: "gray",
        label: "Never"
      },
      error: {
        color: "orange",
        label: "Not found"
      }
    };
</script>

<Label.Single item={intervalInfo[updateInterval ?? "error"]}></Label.Single>
