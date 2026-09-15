<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { Input } from "@eneo/ui";
  import { LockKeyhole } from "lucide-svelte";
  import type { CapabilityDescriptor, CapabilityPurpose } from "$lib/features/mcp/capabilities";
  import { readinessMessage } from "$lib/features/mcp/readiness";
  let {
    capability,
    selectedModel,
    enabledCapabilities = $bindable([])
  }: {
    capability: CapabilityDescriptor;
    selectedModel?: { supports_tool_calling?: boolean } | null;
    enabledCapabilities?: CapabilityPurpose[];
  } = $props();
  const {
    state: { currentSpace }
  } = getSpacesManager();
  const on = $derived(enabledCapabilities.includes(capability.purpose));
  const availability = $derived(
    $currentSpace.available_capabilities?.find((c) => c.purpose === capability.purpose)
  );
  const offered = $derived(($currentSpace.enabled_capabilities ?? []).includes(capability.purpose));
  const blockingMessage = $derived(
    !offered
      ? readinessMessage("space_disabled")
      : selectedModel?.supports_tool_calling === false
        ? m.model_does_not_support_tools()
        : !availability?.available
          ? readinessMessage(availability?.reason ?? "no_active_provider")
          : ""
  );
  function toggle() {
    enabledCapabilities = on
      ? enabledCapabilities.filter((p) => p !== capability.purpose)
      : [...enabledCapabilities, capability.purpose];
  }
</script>

<div
  class="border-default flex items-center gap-3 border-b px-4 py-3 last:border-b-0 {blockingMessage
    ? 'bg-secondary/40'
    : ''}"
>
  <capability.icon class="text-muted h-4 w-4 shrink-0" aria-hidden="true" />
  <Input.Switch
    class="min-w-0 flex-1 [&_button:disabled]:opacity-50"
    value={on}
    disabled={!on && !!blockingMessage}
    sideEffect={toggle}
  >
    <div class="flex flex-col gap-1">
      <span class="flex flex-wrap items-center gap-2">
        <span class="font-medium {blockingMessage ? 'text-secondary' : 'text-default'}"
          >{capability.label()}</span
        >
        {#if blockingMessage}
          <span
            class="bg-warning-dimmer text-warning-stronger inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
          >
            <LockKeyhole class="h-3 w-3" aria-hidden="true" />{m.not_available()}
          </span>
        {/if}
      </span>
      <span class="text-muted text-xs">{blockingMessage || capability.capabilityHint()}</span>
    </div>
  </Input.Switch>
</div>
