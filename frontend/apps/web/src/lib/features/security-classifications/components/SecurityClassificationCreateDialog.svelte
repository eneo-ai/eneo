<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
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
  let showDialog = $state(false);
  const security = getSecurityClassificationService();

  const create = createAsyncState(async () => {
    if (!name) return;
    try {
      await security.createClassification({ name, description });
      showDialog = false;
      name = "";
      description = "";
    } catch (error) {
      toastError(error);
    }
  });
</script>

<Dialog.Root bind:open={showDialog}>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props}>{m.create_new()}</Button>
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        create();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.create_new_security_classification()}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
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
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        <Button type="submit" disabled={create.isLoading}
          >{create.isLoading ? m.creating() : m.create_classification()}</Button
        >
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
