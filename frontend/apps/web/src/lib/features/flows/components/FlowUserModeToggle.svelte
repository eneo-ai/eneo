<script lang="ts">
  import { getFlowUserMode, type FlowUserMode } from "$lib/features/flows/FlowUserMode";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { m } from "$lib/paraglide/messages";

  let {
    showDescription = false
  }: {
    showDescription?: boolean;
  } = $props();

  const mode = getFlowUserMode();
  const activeDescription = $derived(
    $mode === "power_user" ? m.flow_power_user_mode_description() : m.flow_user_mode_description()
  );
</script>

<div class="flex flex-col gap-1.5">
  <Tabs.Root
    value={$mode}
    onValueChange={(v) => mode.set(v as FlowUserMode)}
    class="inline-flex"
    aria-label={m.flow_user_mode_aria_label()}
  >
    <Tabs.List class="h-9">
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
            aria-hidden="true"
          ></span>{/if}
      </Tabs.Trigger>
    </Tabs.List>
  </Tabs.Root>
  {#if showDescription}
    <p class="text-secondary max-w-[28rem] text-xs leading-relaxed">
      {activeDescription}
    </p>
  {/if}
</div>
