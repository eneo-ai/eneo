<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getSpaceSettingsEditor } from "$lib/features/spaces/SpaceSettingsEditor";
  import { Input } from "@intric/ui";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";

  // Get the space settings editor from context (initialized in parent +page.svelte)
  const {
    state: { update, currentChanges },
    discardChanges
  } = getSpaceSettingsEditor();
</script>

<Settings.Row
  title={m.name()}
  description={m.space_name_description()}
  hasChanges={$currentChanges.diff.name !== undefined}
  revertFn={() => discardChanges("name")}
  let:labelId
  let:descriptionId
>
  <Input.Text
    labelClass="text-2xl"
    bind:value={$update.name}
    aria-labelledby={labelId}
    aria-describedby={descriptionId}
  ></Input.Text>
</Settings.Row>

<Settings.Row
  title={m.description()}
  description={m.space_description_description()}
  hasChanges={$currentChanges.diff.description !== undefined}
  revertFn={() => discardChanges("description")}
  let:labelId
  let:descriptionId
>
  <Input.TextArea
    bind:value={$update.description}
    aria-labelledby={labelId}
    aria-describedby={descriptionId}
  ></Input.TextArea>
</Settings.Row>
