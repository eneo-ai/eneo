<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Input } from "@eneo/ui";
  import { LockKeyhole } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import type { CapabilityDescriptor } from "$lib/features/mcp/capabilities";
  import { readinessMessage } from "$lib/features/mcp/readiness";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  let { capability }: { capability: CapabilityDescriptor } = $props();
  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();
  let saving = $state(false);
  let error = $state("");
  const enabled = $derived($currentSpace.enabled_capabilities ?? []);
  const on = $derived(enabled.includes(capability.purpose));
  let switchValue = $derived(on);
  const availability = $derived(
    $currentSpace.available_capabilities?.find((c) => c.purpose === capability.purpose)
  );
  async function toggle() {
    saving = true;
    error = "";
    try {
      await updateSpace({
        enabled_capabilities: on
          ? enabled.filter((p) => p !== capability.purpose)
          : [...enabled, capability.purpose]
      });
    } catch (e) {
      error = getErrorMessage(e);
    } finally {
      switchValue = on;
      saving = false;
    }
  }
</script>

<div
  class="border-default border-b px-4 py-3 last:border-b-0 {!availability?.available
    ? 'bg-secondary/40'
    : ''}"
>
  <div class="flex items-center gap-3">
    <capability.icon class="text-muted h-4 w-4 shrink-0" aria-hidden="true" />
    <Input.Switch
      class="min-w-0 flex-1 [&_button:disabled]:opacity-50"
      bind:value={switchValue}
      disabled={saving || (!on && !availability?.available)}
      sideEffect={toggle}
    >
      <div class="flex flex-col gap-1">
        <span class="flex flex-wrap items-center gap-2">
          <span class="font-medium {availability?.available ? 'text-default' : 'text-secondary'}"
            >{capability.label()}</span
          >
          {#if !availability?.available}
            <span
              class="bg-warning-dimmer text-warning-stronger inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
            >
              <LockKeyhole class="h-3 w-3" aria-hidden="true" />{m.not_available()}
            </span>
          {/if}
        </span>
        <span class="text-muted text-xs"
          >{availability?.available
            ? capability.spaceHint()
            : readinessMessage(availability?.reason ?? "no_active_provider")}</span
        >
      </div>
    </Input.Switch>
  </div>
  {#if error}<p class="text-negative-default mt-2 ml-7 text-sm" role="alert">{error}</p>{/if}
</div>
