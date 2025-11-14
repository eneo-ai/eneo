<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Button } from "@intric/ui";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import RetentionPolicyInput from "$lib/components/settings/RetentionPolicyInput.svelte";

  const spaces = getSpacesManager();
  const currentSpace = spaces.state.currentSpace;

  let currentRetentionDays: number | null = null;

  function watch(space: { data_retention_days?: number | null }) {
    currentRetentionDays = space.data_retention_days ?? null;
  }

  $: watch($currentSpace);
</script>

<Settings.Row
  title={m.conversation_retention_title()}
  description={m.conversation_retention_space_description()}
  let:labelId
  let:descriptionId
>
  <RetentionPolicyInput
    bind:value={currentRetentionDays}
    {labelId}
    {descriptionId}
  />
  <div class="mt-4 flex justify-end gap-3">
    <Button
      variant="outlined"
      on:click={() => {
        currentRetentionDays = $currentSpace.data_retention_days;
      }}>{m.revert_changes()}</Button
    >
    <Button
      variant="primary"
      on:click={() => {
        spaces.updateSpace({ data_retention_days: currentRetentionDays });
      }}>{m.save_changes()}</Button
    >
  </div>
</Settings.Row>
