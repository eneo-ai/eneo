<script lang="ts">
  import type { WebsiteSparse } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let updateInterval: WebsiteSparse["update_interval"];
  /* TODO colours */
  const intervalInfo: Record<string, { label: string; color: Label.LabelColor; tooltip?: string }> =
    {
      weekly: {
        color: "green",
        label: m.weekly()
      },
      never: {
        color: "gray",
        label: m.never()
      },
      error: {
        color: "orange",
        label: m.not_found()
      }
    };
</script>

<Label.Single item={intervalInfo[updateInterval ?? "error"]}></Label.Single>
