<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog, Dropdown, Input } from "@intric/ui";
  import { writable } from "svelte/store";
  import { getSecurityClassificationService } from "../SecurityClassificationsService.svelte";
  import { IntricError, type SecurityClassification } from "@intric/intric-js";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { IconTrash } from "@intric/icons/trash";
  import { IconEdit } from "@intric/icons/edit";
  import { IconArrowUpToLine } from "@intric/icons/arrow-up-to-line";
  import { IconArrowDownToLine } from "@intric/icons/arrow-down-to-line";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    classification: SecurityClassification;
  };

  const { classification }: Props = $props();
  let name = $derived(classification.name);
  let description = $derived(classification.description ?? "");
  let hasChanges = $derived(
    classification.name !== name || classification.description !== description
  );

  const security = getSecurityClassificationService();
  const showDeleteDialog = writable(false);
  const showEditDialog = writable(false);

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
      $showDeleteDialog = false;
    } catch (error) {
      alert(error instanceof IntricError ? error.getReadableMessage() : String(error));
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
      $showEditDialog = false;
    } catch (error) {
      alert(error instanceof IntricError ? error.getReadableMessage() : String(error));
    }
  });
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button is={trigger} disabled={false} padding="icon">
      <IconEllipsis></IconEllipsis>
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <Button
      is={item}
      onclick={() => {
        security.move(classification, "up");
      }}
      disabled={isHighest}
      padding="icon-leading"
    >
      <IconArrowUpToLine size="sm" />
      {m.move_up()}
    </Button>
    <Button
      is={item}
      onclick={() => {
        security.move(classification, "down");
      }}
      disabled={isLowest}
      padding="icon-leading"
    >
      <IconArrowDownToLine size="sm" />
      {m.move_down()}
    </Button>
    <Button
      is={item}
      onclick={() => {
        $showEditDialog = true;
      }}
      padding="icon-leading"
    >
      <IconEdit size="sm" />
      {m.edit()}
    </Button>
    <Button
      is={item}
      variant="destructive"
      onclick={() => {
        $showDeleteDialog = true;
      }}
      padding="icon-leading"
    >
      <IconTrash size="sm"></IconTrash>{m.delete()}</Button
    >
  </Dropdown.Menu>
</Dropdown.Root>

<Dialog.Root openController={showDeleteDialog}>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.delete_security_classification()}</Dialog.Title>

    <Dialog.Description>
      {m.confirm_delete_classification({ name: classification.name })}
    </Dialog.Description>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" onclick={remove} type="submit" disabled={remove.isLoading}
        >{remove.isLoading ? m.deleting() : m.delete_classification()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root openController={showEditDialog}>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.edit_security_classification()}</Dialog.Title>

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
      <Button
        variant="primary"
        onclick={update}
        type="submit"
        disabled={update.isLoading || !hasChanges}
        >{update.isLoading ? m.updating() : m.update_classification()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
