<script lang="ts">
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { m } from "$lib/paraglide/messages";

  const mode = getFlowUserMode();
</script>

<div class="border-default flex h-8 items-center rounded-lg border shadow-sm text-xs font-medium">
  <button
    class="h-full rounded-l-lg px-3.5 transition-all duration-150"
    class:bg-hover-dimmer={$mode === "user"}
    class:shadow-inner={$mode === "user"}
    class:text-primary={$mode === "user"}
    class:text-secondary={$mode !== "user"}
    on:click={() => mode.set("user")}
  >
    {m.flow_user_mode()}
  </button>
  <div class="border-default h-full w-px border-l"></div>
  <button
    class="h-full rounded-r-lg px-3.5 transition-all duration-150"
    class:bg-hover-dimmer={$mode === "power_user"}
    class:shadow-inner={$mode === "power_user"}
    class:text-primary={$mode === "power_user"}
    class:text-secondary={$mode !== "power_user"}
    on:click={() => mode.set("power_user")}
  >
    {m.flow_power_user_mode()}
  </button>
</div>
