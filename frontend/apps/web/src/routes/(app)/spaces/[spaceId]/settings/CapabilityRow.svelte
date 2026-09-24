<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { LockKeyhole } from "@lucide/svelte";
  import { m } from "$lib/paraglide/messages";
  import type { CapabilityDescriptor } from "$lib/features/mcp/capabilities";
  import { readinessMessage } from "$lib/features/mcp/readiness";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  let { capability }: { capability: CapabilityDescriptor } = $props();
  const uid = $props.id();
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
    <Field.Field orientation="horizontal" class="min-w-0 flex-1">
      <Field.Content>
        <Field.Label for={`${uid}-switch`} class="flex-wrap">
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
        </Field.Label>
        <Field.Description id={`${uid}-hint`} class="text-muted text-xs"
          >{availability?.available
            ? capability.spaceHint()
            : readinessMessage(availability?.reason ?? "no_active_provider")}</Field.Description
        >
      </Field.Content>
      <Switch
        id={`${uid}-switch`}
        bind:checked={switchValue}
        disabled={saving || (!on && !availability?.available)}
        onCheckedChange={toggle}
        aria-describedby={`${uid}-hint`}
      />
    </Field.Field>
  </div>
  {#if error}<p class="text-negative-default mt-2 ml-7 text-sm" role="alert">{error}</p>{/if}
</div>
