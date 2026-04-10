<script lang="ts">
  import { onMount } from "svelte";
  import { Clock } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { createDateFormatter } from "$lib/features/api-keys/apiKeyTableUtils";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";

  let { graceUntil }: { graceUntil: string } = $props();

  const formatter = createDateFormatter();
  let now = $state(Date.now());

  const hoursRemaining = $derived.by(() => {
    const until = new Date(graceUntil).getTime();
    const diffMs = until - now;
    if (diffMs <= 0) return 0;
    return Math.ceil(diffMs / (1000 * 60 * 60));
  });

  const isExpired = $derived(hoursRemaining <= 0);
  const formattedDate = $derived(formatter.format(new Date(graceUntil)));

  onMount(() => {
    const interval = setInterval(() => {
      now = Date.now();
    }, 60_000);

    return () => clearInterval(interval);
  });
</script>

{#if !isExpired}
  <Tooltip.Provider>
    <Tooltip.Root>
      <Tooltip.Trigger>
        <div
          class="text-warning-stronger bg-warning-dimmer/40 border-warning-default/30 inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium"
        >
          <Clock class="h-3 w-3" />
          {m.api_keys_grace_remaining({ hours: hoursRemaining })}
        </div>
      </Tooltip.Trigger>
      <Tooltip.Content>
        <p>{m.api_keys_grace_tooltip({ date: formattedDate })}</p>
      </Tooltip.Content>
    </Tooltip.Root>
  </Tooltip.Provider>
{/if}
