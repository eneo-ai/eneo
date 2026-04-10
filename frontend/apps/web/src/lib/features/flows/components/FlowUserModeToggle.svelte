<script lang="ts">
  import { getFlowUserMode, type FlowUserMode } from "$lib/features/flows/FlowUserMode";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { m } from "$lib/paraglide/messages";

  const mode = getFlowUserMode();
</script>

<Tabs.Root value={$mode} onValueChange={(v) => mode.set(v as FlowUserMode)} class="inline-flex">
  <Tabs.List class="h-8">
    <Tabs.Trigger value="user" title={m.flow_user_mode_tooltip()} class="px-3 py-1 text-xs">
      {m.flow_user_mode()}
    </Tabs.Trigger>
    <Tabs.Trigger
      value="power_user"
      title={m.flow_power_user_mode_tooltip()}
      class="px-3 py-1 text-xs"
    >
      {m.flow_power_user_mode()}
      {#if $mode === "power_user"}<span
          class="bg-warning-default ml-1 inline-block size-1.5 rounded-full"
        ></span>{/if}
    </Tabs.Trigger>
  </Tabs.List>
</Tabs.Root>
