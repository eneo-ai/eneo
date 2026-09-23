<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog } from "@eneo/ui";
  import { writable } from "svelte/store";
  import { getSecurityClassificationService } from "../SecurityClassificationsService.svelte";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";

  const uid = $props.id();
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
      toastError(error);
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
      <Field.Field class="border-default hover:bg-hover-dimmer border-b p-4">
        <Field.Label for={`${uid}-name`}>
          {m.name()}
          <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
        </Field.Label>
        <Input
          id={`${uid}-name`}
          bind:value={name}
          required
          aria-describedby={`${uid}-name-description`}
        />
        <Field.Description id={`${uid}-name-description`}>
          {m.recognisable_display_name()}
        </Field.Description>
      </Field.Field>

      <Field.Field class="border-default hover:bg-hover-dimmer border-b p-4">
        <Field.Label for={`${uid}-description`}>{m.description()}</Field.Label>
        <Textarea
          id={`${uid}-description`}
          bind:value={description}
          rows={4}
          aria-describedby={`${uid}-description-description`}
        />
        <Field.Description id={`${uid}-description-description`}>
          {m.describe_when_classification_chosen()}
        </Field.Description>
      </Field.Field>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" onclick={create} type="submit" disabled={create.isLoading}
        >{create.isLoading ? m.creating() : m.create_classification()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
