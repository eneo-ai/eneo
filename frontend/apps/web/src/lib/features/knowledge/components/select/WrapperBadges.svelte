<script lang="ts">
  import type { IntegrationKnowledge } from "@intric/intric-js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getWrapperCountBadges, type WrapperCountBadge } from "./knowledgeIntegration";

  type Props = { items: IntegrationKnowledge[] };
  let { items }: Props = $props();

  const badges = $derived(getWrapperCountBadges(items));

  function label({ type, count }: WrapperCountBadge): string {
    const one = count === 1;
    switch (type) {
      case "files":
        return one
          ? m.sharepoint_wrapper_files_one({ count })
          : m.sharepoint_wrapper_files_other({ count });
      case "folders":
        return one
          ? m.sharepoint_wrapper_folders_one({ count })
          : m.sharepoint_wrapper_folders_other({ count });
      case "sites":
        return one
          ? m.sharepoint_wrapper_sites_one({ count })
          : m.sharepoint_wrapper_sites_other({ count });
      case "items":
        return one
          ? m.sharepoint_wrapper_items_one({ count })
          : m.sharepoint_wrapper_items_other({ count });
    }
  }
</script>

<div class="flex items-center gap-2">
  {#each badges as badge (badge.type)}
    <Badge variant="outline" class="text-muted font-normal">{label(badge)}</Badge>
  {/each}
</div>
