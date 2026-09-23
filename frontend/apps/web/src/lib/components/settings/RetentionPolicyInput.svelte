<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    value: number | null | undefined;
    hasChanges?: boolean;
    inheritedDays?: number | null;
    inheritedFrom?: "space" | "tenant" | null;
    labelId?: string;
    descriptionId?: string;
  }

  /* eslint-disable @typescript-eslint/no-unused-vars -- props are part of component's public API */
  let {
    value = $bindable(),
    hasChanges = false,
    inheritedDays = null,
    inheritedFrom = null,
    labelId,
    descriptionId
  }: Props = $props();
  /* eslint-enable @typescript-eslint/no-unused-vars */

  const uid = $props.id();

  // Track if override is enabled
  let isOverrideEnabled = $state(value !== null);

  function handleSwitchChange(next: boolean) {
    if (next) {
      // Enable override - set default value
      value = inheritedDays ?? 365;
    } else {
      // Disable override - inherit from parent
      value = null;
    }
    isOverrideEnabled = next;
  }

  // Local non-null value for the number input binding
  let inputValue = $state(value ?? 365);

  // Sync state if value changes externally
  $effect(() => {
    isOverrideEnabled = value !== null;
    if (value !== null && value !== undefined) inputValue = value;
  });

  // Sync input changes back to value
  $effect(() => {
    if (isOverrideEnabled) value = inputValue;
  });
</script>

<div class="border-default flex flex-col gap-3 rounded-lg border p-4">
  <!-- Switch to enable override -->
  <Field.Field orientation="horizontal">
    <Field.Label for={`${uid}-override`}>
      <span class="text-sm">
        {m.conversation_retention_override_label()}
        {#if inheritedDays !== null}
          <span class="text-muted">({inheritedDays} {m.conversation_retention_days()})</span>
        {/if}
      </span>
    </Field.Label>
    <Switch
      id={`${uid}-override`}
      checked={isOverrideEnabled}
      onCheckedChange={handleSwitchChange}
    />
  </Field.Field>

  <!-- Input field (only shown when override is enabled) -->
  {#if isOverrideEnabled}
    <div class="border-default flex items-center gap-2 border-t pt-2">
      <Input
        type="number"
        bind:value={inputValue}
        min={1}
        max={2555}
        step={1}
        aria-label={m.number_of_days()}
        aria-describedby={descriptionId}
        class="w-[140px] text-center"
        oninput={() => {
          if (inputValue > 2555) inputValue = 2555;
          else if (inputValue < 1) inputValue = 1;
        }}
      />
      <span class="text-default-dimmer text-sm">{m.conversation_retention_days()}</span>
    </div>
  {/if}
</div>
