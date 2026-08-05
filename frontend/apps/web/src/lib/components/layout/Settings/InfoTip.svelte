<script lang="ts">
  import Info from "lucide-svelte/icons/info";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";

  let { text, title }: { text: string; title: string } = $props();
</script>

<Tooltip.Root delayDuration={150}>
  <Tooltip.Trigger
    class="text-secondary hover:text-primary focus-visible:ring-ring/50 ml-2 inline-flex size-6 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none"
    aria-label={m.flow_settings_more_info({ title })}
    type="button"
  >
    <Info class="size-4" aria-hidden="true" />
  </Tooltip.Trigger>
  <Tooltip.Content class="max-w-xs text-pretty" side="top" align="start">
    {text}
  </Tooltip.Content>
</Tooltip.Root>
