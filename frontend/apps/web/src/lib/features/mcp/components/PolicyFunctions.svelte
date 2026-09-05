<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import { getCapability } from "$lib/features/mcp/capabilities";
  import { readinessMessage } from "$lib/features/mcp/readiness";
  let {
    config,
    selectedModel
  }: {
    config: Pick<
      components["schemas"]["EffectiveConfigPublic"],
      "enabled_capabilities" | "available_capabilities" | "default_disabled_capabilities"
    >;
    selectedModel?: { supports_tool_calling?: boolean } | null;
  } = $props();
</script>

{#if config.enabled_capabilities?.length}
  <ul class="border-default divide-default divide-y overflow-hidden rounded-xl border">
    {#each config.enabled_capabilities as purpose (purpose)}
      {@const capability = getCapability(purpose)}
      {@const availability = config.available_capabilities?.find(
        (entry) => entry.purpose === purpose
      )}
      <li class="flex items-center gap-3 px-4 py-3">
        {#if capability}<capability.icon
            class="text-muted h-4 w-4 shrink-0"
            aria-hidden="true"
          />{/if}
        <div class="min-w-0">
          <p class="text-default font-medium">{capability?.label() ?? purpose}</p>
          <p class="text-muted mt-1 text-xs">
            {config.default_disabled_capabilities?.includes(purpose)
              ? m.functions_default_off()
              : m.functions_default_on()}
          </p>
          {#if selectedModel?.supports_tool_calling === false}
            <p class="text-muted mt-1 text-xs">{m.model_does_not_support_tools()}</p>
          {:else if !availability?.available}
            <p class="text-muted mt-1 text-xs">
              {readinessMessage(availability?.reason ?? "no_active_provider")}
            </p>
          {/if}
        </div>
      </li>
    {/each}
  </ul>
{:else}
  <p class="text-muted text-sm">{m.functions_policy_none()}</p>
{/if}
