<script lang="ts">
  import type { WebsiteSparse } from "@intric/intric-js";
  import { Label } from "@intric/ui";

  export let updateInterval: WebsiteSparse["update_interval"];

  const intervalInfo: Record<string, { label: string; color: Label.LabelColor; tooltip?: string }> = {
    never: {
      color: "gray",
      label: "Never"
    },
    daily: {
      color: "green",
      label: "Daily",
      tooltip: "Recrawls every day at 3 AM Swedish time"
    },
    every_other_day: {
      color: "green",
      label: "Every other day",
      tooltip: "Recrawls every 2 days at 3 AM Swedish time"
    },
    weekly: {
      color: "green",
      label: "Weekly",
      tooltip: "Recrawls every Friday at 3 AM Swedish time"
    },
    error: {
      color: "orange",
      label: "Not found"
    }
  };
</script>

<Label.Single item={intervalInfo[updateInterval ?? "error"]}></Label.Single>
