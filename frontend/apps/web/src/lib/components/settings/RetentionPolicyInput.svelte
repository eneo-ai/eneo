<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    value: number | null;
    hasChanges?: boolean;
    inheritedDays?: number | null;
    inheritedFrom?: "space" | "tenant" | null;
    labelId?: string;
    descriptionId?: string;
  }

  let {
    value = $bindable(),
    hasChanges = false,
    inheritedDays = null,
    inheritedFrom = null,
    labelId,
    descriptionId
  }: Props = $props();

  // Track if override is enabled
  let isOverrideEnabled = $state(value !== null);

  function handleSwitchChange({ next }: { current: boolean; next: boolean }) {
    if (next) {
      // Enable override - set default value
      value = inheritedDays ?? 365;
    } else {
      // Disable override - inherit from parent
      value = null;
    }
    isOverrideEnabled = next;
  }

  // Sync state if value changes externally
  $effect(() => {
    isOverrideEnabled = value !== null;
  });
</script>

<div class="rounded-lg border border-default p-4 flex flex-col gap-3">
  <!-- Switch to enable override -->
  <Input.Switch
    value={isOverrideEnabled}
    sideEffect={handleSwitchChange}
  >
    <span class="text-sm">
      {m.conversation_retention_override_label()}
      {#if inheritedDays !== null}
        <span class="text-muted">({inheritedDays} {m.conversation_retention_days()})</span>
      {/if}
    </span>
  </Input.Switch>

  <!-- Input field (only shown when override is enabled) -->
  {#if isOverrideEnabled}
    <div class="flex items-center gap-2 pt-2 border-t border-default">
      <Input.Number
        bind:value
        min={1}
        max={2555}
        aria-label={m.number_of_days()}
        aria-describedby={descriptionId}
        class="w-[140px]"
      />
      <span class="text-default-dimmer text-sm">{m.conversation_retention_days()}</span>
    </div>
  {/if}
</div>
