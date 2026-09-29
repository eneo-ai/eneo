<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { getSecurityClassificationService } from "../SecurityClassificationsService.svelte";
  import { type SecurityClassification } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconArrowUpToLine } from "@eneo/icons/arrow-up-to-line";
  import { IconArrowDownToLine } from "@eneo/icons/arrow-down-to-line";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  type Props = {
    classification: SecurityClassification;
  };

  const { classification }: Props = $props();
  const uid = $props.id();
  let name = $derived(classification.name);
  let description = $derived(classification.description ?? "");
  let hasChanges = $derived(
    classification.name !== name || classification.description !== description
  );

  const security = getSecurityClassificationService();
  let showDeleteDialog = $state(false);
  let showEditDialog = $state(false);

  // This is a bit counter intuitive as the classifications array has the highest class first (index 0)
  // Because we want to render it first, whereas the backend (and service internally) has it the other way round.
  const isHighest = $derived(
    security.classifications.findIndex(({ id }) => id === classification.id) === 0
  );
  const isLowest = $derived(
    security.classifications.findIndex(({ id }) => id === classification.id) ===
      security.classifications.length - 1
  );

  const remove = createAsyncState(async () => {
    try {
      await security.deleteClassification(classification);
      showDeleteDialog = false;
    } catch (error) {
      toastError(error);
    }
  });

  const update = createAsyncState(async () => {
    try {
      await security.updateClassification({
        id: classification.id,
        name: name === classification.name ? undefined : name,
        // Need to keep in mind description can be null, but defaults to empty string
        description: description === (classification.description ?? "") ? undefined : description
      });
      showEditDialog = false;
    } catch (error) {
      toastError(error);
    }
  });
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
        <IconEllipsis></IconEllipsis>
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end">
    <DropdownMenu.Item
      onSelect={() => {
        security.move(classification, "up");
      }}
      disabled={isHighest}
    >
      <IconArrowUpToLine size="sm" />
      {m.move_up()}
    </DropdownMenu.Item>
    <DropdownMenu.Item
      onSelect={() => {
        security.move(classification, "down");
      }}
      disabled={isLowest}
    >
      <IconArrowDownToLine size="sm" />
      {m.move_down()}
    </DropdownMenu.Item>
    <DropdownMenu.Item
      onSelect={() => {
        showEditDialog = true;
      }}
    >
      <IconEdit size="sm" />
      {m.edit()}
    </DropdownMenu.Item>
    <DropdownMenu.Item
      variant="destructive"
      onSelect={() => {
        showDeleteDialog = true;
      }}
    >
      <IconTrash size="sm"></IconTrash>{m.delete()}</DropdownMenu.Item
    >
  </DropdownMenu.Content>
</DropdownMenu.Root>

<Dialog.Root bind:open={showDeleteDialog}>
  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        remove();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.delete_security_classification()}</Dialog.Title>
        <Dialog.Description>
          {m.confirm_delete_classification({ name: classification.name })}
        </Dialog.Description>
      </Dialog.Header>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        <Button variant="destructive" type="submit" disabled={remove.isLoading}
          >{remove.isLoading ? m.deleting() : m.delete_classification()}</Button
        >
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={showEditDialog}>
  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        update();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.edit_security_classification()}</Dialog.Title>
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
        <Button type="submit" disabled={update.isLoading || !hasChanges}
          >{update.isLoading ? m.updating() : m.update_classification()}</Button
        >
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
