<script lang="ts">
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { m } from "$lib/paraglide/messages";

  const mode = getFlowUserMode();
</script>

<div class="inline-flex items-center rounded-lg border border-default bg-secondary/50 p-0.5">
  <button
    class="rounded-md px-3.5 py-1.5 text-sm font-medium transition-all duration-200"
    class:bg-primary={$mode !== "power_user"}
    class:shadow-sm={$mode !== "power_user"}
    class:text-primary={$mode !== "power_user"}
    class:text-muted={$mode === "power_user"}
    on:click={() => mode.set("user")}
    title={m.flow_user_mode_tooltip()}
  >
    {m.flow_user_mode()}
  </button>
  <button
    class="rounded-md px-3.5 py-1.5 text-sm font-medium transition-all duration-200"
    class:bg-primary={$mode === "power_user"}
    class:shadow-sm={$mode === "power_user"}
    class:text-primary={$mode === "power_user"}
    class:text-muted={$mode !== "power_user"}
    on:click={() => mode.set("power_user")}
    title={m.flow_power_user_mode_tooltip()}
  >
    {m.flow_power_user_mode()}
    {#if $mode === "power_user"}<span class="ml-1 inline-block size-1.5 rounded-full bg-amber-400"></span>{/if}
  </button>
</div>
