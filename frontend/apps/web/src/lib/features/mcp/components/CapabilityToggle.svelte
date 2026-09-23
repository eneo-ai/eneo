<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
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
  const uid = $props.id();
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
  <Field.Field orientation="horizontal" class="min-w-0 flex-1 gap-4">
    <Field.Content class="gap-1">
      <Field.Label for={`${uid}-switch`} class="flex-wrap">
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
      </Field.Label>
      <Field.Description id={`${uid}-hint`} class="text-muted text-xs">
        {blockingMessage || capability.capabilityHint()}
      </Field.Description>
    </Field.Content>
    <Switch
      id={`${uid}-switch`}
      checked={on}
      disabled={!on && !!blockingMessage}
      onCheckedChange={toggle}
      aria-describedby={`${uid}-hint`}
    />
  </Field.Field>
</div>
