<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpaceSettingsEditor } from "$lib/features/spaces/SpaceSettingsEditor";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import RetentionPolicyInput from "$lib/components/settings/RetentionPolicyInput.svelte";

  // Get the space settings editor from context (initialized in parent +page.svelte)
  const {
    state: { update, currentChanges },
    discardChanges
  } = getSpaceSettingsEditor();
</script>

<Settings.Row
  title={m.conversation_retention_title()}
  description={m.conversation_retention_space_description()}
  hasChanges={$currentChanges.diff.data_retention_days !== undefined}
  revertFn={() => discardChanges("data_retention_days")}
  let:labelId
  let:descriptionId
>
  <RetentionPolicyInput bind:value={$update.data_retention_days} {labelId} {descriptionId} />
</Settings.Row>

<Settings.Row
  title={m.space_flow_retention_title()}
  description={m.space_flow_retention_description()}
>
  <div class="border-default bg-secondary rounded-md border px-3 py-2.5 text-sm">
    <span class="text-secondary">{m.space_flow_retention_configured()}</span>
    <span class="text-primary ml-2 font-medium tabular-nums">
      {$update.data_retention_days === null || $update.data_retention_days === undefined
        ? m.flow_retention_not_configured()
        : m.flow_retention_days_value({ days: $update.data_retention_days })}
    </span>
  </div>
</Settings.Row>
