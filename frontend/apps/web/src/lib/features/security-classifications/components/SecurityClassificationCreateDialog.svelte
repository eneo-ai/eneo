<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog, Input } from "@intric/ui";
  import { writable } from "svelte/store";
  import { getSecurityClassificationService } from "../SecurityClassificationsService.svelte";
  import { IntricError } from "@intric/intric-js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";

  let name = $state("");
  let description = $state("");
  const showDialog = writable(false);
  const security = getSecurityClassificationService();

  const create = createAsyncState(async () => {
    if (!name) return;
    try {
      await security.createClassification({ name, description });
      $showDialog = false;
      name = "";
      description = "";
    } catch (error) {
      alert(error instanceof IntricError ? error.getReadableMessage() : String(error));
    }
  });
</script>

<Dialog.Root openController={showDialog}>
  <Dialog.Trigger asFragment let:trigger>
    <Button variant="primary" is={trigger}>{m.create_new()}</Button>
  </Dialog.Trigger>

  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.create_new_security_classification()}</Dialog.Title>

    <Dialog.Section>
      <Input.Text
        bind:value={name}
        label={m.name()}
        description={m.recognisable_display_name()}
        required
        class="border-default hover:bg-hover-dimmer border-b p-4"
      ></Input.Text>

      <Input.TextArea
        label={m.description()}
        class="border-default hover:bg-hover-dimmer border-b p-4"
        description={m.describe_when_classification_chosen()}
        bind:value={description}
      ></Input.TextArea>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" onclick={create} type="submit" disabled={create.isLoading}
        >{create.isLoading ? m.creating() : m.create_classification()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
