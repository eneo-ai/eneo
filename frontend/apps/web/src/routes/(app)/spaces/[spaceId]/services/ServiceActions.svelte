<script lang="ts">
  import type { ServiceSparse } from "@eneo/eneo-js";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconMove } from "@eneo/icons/move";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { useId } from "bits-ui";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let service: ServiceSparse;

  const {
    state: { currentSpace, accessibleSpaces },
    refreshCurrentSpace
  } = getSpacesManager();

  const eneo = getEneo();
  async function deleteService() {
    isProcessing = true;
    try {
      await eneo.services.delete(service);
      refreshCurrentSpace();
      showDeleteDialog = false;
    } catch (e) {
      toastError(e, m.could_not_delete_service());
      console.error(e);
    }
    isProcessing = false;
  }

  async function moveService() {
    if (!moveDestination) return;
    isProcessing = true;
    try {
      await eneo.services.transfer({
        service,
        moveResources: false,
        targetSpace: moveDestination
      });
      refreshCurrentSpace();
      showMoveDialog = false;
    } catch (e) {
      toastError(e);
      console.error(e);
    }
    isProcessing = false;
  }

  let isProcessing = false;
  let showDeleteDialog = false;
  let showMoveDialog = false;
  const destinationId = useId();

  const moveTargets = derived(accessibleSpaces, ($accessibleSpaces) => {
    return $accessibleSpaces.reduce(
      (acc, curr) => {
        if (curr.id !== $currentSpace.id) {
          acc.push({ label: curr.name, value: { id: curr.id } });
        }
        return acc;
      },
      [] as Array<{ label: string; value: { id: string } }>
    );
  });
  let moveDestination: { id: string } | undefined = undefined;

  let showActions = (["edit", "delete"] as const).some((permission) =>
    service.permissions?.includes(permission)
  );
</script>

{#if showActions}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
          <IconEllipsis />
        </Button>
      {/snippet}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end">
      {#if service.permissions?.includes("edit")}
        <DropdownMenu.Item>
          {#snippet child({ props })}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
            <a
              {...props}
              href={localizeHref(
                `/spaces/${$currentSpace.routeId}/services/${service.id}?tab=edit`
              )}
            >
              <IconEdit size="sm" />
              {m.edit()}
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {/snippet}
        </DropdownMenu.Item>
      {/if}
      {#if service.permissions?.includes("delete")}
        <DropdownMenu.Item onSelect={() => (showMoveDialog = true)}>
          <IconMove size="sm" />
          {m.move()}
        </DropdownMenu.Item>
        <DropdownMenu.Item variant="destructive" onSelect={() => (showDeleteDialog = true)}>
          <IconTrash size="sm" />{m.delete()}
        </DropdownMenu.Item>
      {/if}
    </DropdownMenu.Content>
  </DropdownMenu.Root>
{/if}

<AlertDialog.Root bind:open={showDeleteDialog}>
  <AlertDialog.Content class={dialogLayout.content()}>
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title>{m.delete_service()}</AlertDialog.Title>
      <AlertDialog.Description
        >{m.confirm_delete_service({ serviceName: service.name })}</AlertDialog.Description
      >
    </AlertDialog.Header>

    <AlertDialog.Footer class={dialogLayout.footer}>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button variant="destructive" onclick={deleteService}
        >{isProcessing ? m.deleting() : m.delete()}</Button
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<Dialog.Root bind:open={showMoveDialog}>
  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        moveService();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.move_service()}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <Field.Field class="border-default hover:bg-hover-dimmer rounded-t-md border-b px-4 py-4">
            <Field.Label for={destinationId}>{m.destination()}</Field.Label>
            <Select.Root
              type="single"
              name="destination"
              required
              value={moveDestination?.id}
              onValueChange={(id) =>
                (moveDestination =
                  $moveTargets.find((option) => option.value.id === id)?.value ?? moveDestination)}
            >
              <Select.Trigger id={destinationId} class="w-full">
                {$moveTargets.find((option) => option.value.id === moveDestination?.id)?.label ??
                  m.ui_select_placeholder()}
              </Select.Trigger>
              <Select.Content>
                {#each $moveTargets as option (option.value.id)}
                  <Select.Item value={option.value.id} label={option.label}
                    >{option.label}</Select.Item
                  >
                {:else}
                  <Select.Item
                    value=""
                    disabled
                    label={m.ui_no_available_items({ resourceName: m.resource_spaces() })}
                  >
                    {m.ui_no_available_items({ resourceName: m.resource_spaces() })}
                  </Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
          </Field.Field>
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        <Button type="submit" variant="destructive"
          >{isProcessing ? m.moving() : m.move_service()}</Button
        >
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
