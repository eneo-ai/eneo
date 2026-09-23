<script lang="ts">
  import type { AssistantSparse } from "@eneo/eneo-js";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconMove } from "@eneo/icons/move";
  import { useId } from "bits-ui";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived, writable } from "svelte/store";
  import PublishingDialog from "$lib/features/publishing/components/PublishingDialog.svelte";
  import { IconArrowUpToLine } from "@eneo/icons/arrow-up-to-line";
  import { IconArrowDownToLine } from "@eneo/icons/arrow-down-to-line";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let assistant: AssistantSparse;

  const {
    state: { currentSpace, accessibleSpaces },
    refreshCurrentSpace
  } = getSpacesManager();

  const eneo = getEneo();

  async function deleteAssistant() {
    isProcessing = true;
    try {
      await eneo.assistants.delete(assistant);
      refreshCurrentSpace("applications");
      showDeleteDialog = false;
    } catch (e) {
      toastError(e, m.could_not_delete_assistant());
      console.error(e);
    }
    isProcessing = false;
  }

  async function moveAssistant() {
    if (!moveDestination) return;
    isProcessing = true;
    try {
      await eneo.assistants.transfer({ assistant, moveResources, targetSpace: moveDestination });
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
  const showPublishDialog = writable(false);

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
  let moveResources: boolean = false;
  const moveDestinationId = useId();
  const moveResourcesId = useId();

  $: moveDestinationLabel = $moveTargets.find(
    (target) => target.value.id === moveDestination?.id
  )?.label;

  let showActions = (["edit", "publish", "delete"] as const).some((permission) =>
    assistant.permissions?.includes(permission)
  );
</script>

{#if showActions}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button
          {...props}
          variant="ghost"
          size="icon"
          class="hover:bg-hover-on-fill hover:text-primary"
          aria-label={m.actions()}
        >
          <IconEllipsis />
        </Button>
      {/snippet}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end">
      {#if assistant.permissions?.includes("edit")}
        <DropdownMenu.Item>
          {#snippet child({ props })}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
            <a
              {...props}
              href={localizeHref(
                `/spaces/${$currentSpace.routeId}/assistants/${assistant.id}/edit`
              )}
            >
              <IconEdit size="sm" />
              {m.edit()}
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {/snippet}
        </DropdownMenu.Item>
      {/if}
      {#if assistant.permissions?.includes("publish")}
        <DropdownMenu.Item
          onSelect={() => {
            $showPublishDialog = true;
          }}
        >
          {#if assistant.published}
            <IconArrowDownToLine size="sm"></IconArrowDownToLine>
            {m.unpublish()}
          {:else}
            <IconArrowUpToLine size="sm"></IconArrowUpToLine>
            {m.publish()}
          {/if}
        </DropdownMenu.Item>
      {/if}
      {#if assistant.permissions?.includes("delete")}
        <DropdownMenu.Item
          onSelect={() => {
            showMoveDialog = true;
          }}
        >
          <IconMove size="sm" />
          {m.move()}
        </DropdownMenu.Item>
        <DropdownMenu.Item
          variant="destructive"
          onSelect={() => {
            showDeleteDialog = true;
          }}
        >
          <IconTrash size="sm" />{m.delete()}
        </DropdownMenu.Item>
      {/if}
    </DropdownMenu.Content>
  </DropdownMenu.Root>
{/if}

<AlertDialog.Root bind:open={showDeleteDialog}>
  <AlertDialog.Content class={dialogLayout.content("small")}>
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title>{m.delete_assistant()}</AlertDialog.Title>
      <AlertDialog.Description
        >{m.confirm_delete_assistant({ name: assistant.name })}</AlertDialog.Description
      >
    </AlertDialog.Header>

    <AlertDialog.Footer class={dialogLayout.footer}>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button variant="destructive" onclick={deleteAssistant}
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
        moveAssistant();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.move_assistant()}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <Field.Field class="border-default hover:bg-hover-dimmer rounded-t-md border-b px-4 py-4">
            <Field.Label for={moveDestinationId}>{m.destination()}</Field.Label>
            <Select.Root
              type="single"
              name="destination"
              required
              value={moveDestination?.id ?? ""}
              onValueChange={(id) =>
                (moveDestination =
                  $moveTargets.find((target) => target.value.id === id)?.value ?? moveDestination)}
            >
              <Select.Trigger id={moveDestinationId} class="w-full">
                {moveDestinationLabel ?? m.ui_select_placeholder()}
              </Select.Trigger>
              <Select.Content>
                {#each $moveTargets as target (target.value.id)}
                  <Select.Item value={target.value.id} label={target.label}>
                    {target.label}
                  </Select.Item>
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
          <Field.Field orientation="horizontal" class="hover:bg-hover-dimmer px-4 py-4">
            <Field.Label for={moveResourcesId}>{m.include_assistants_knowledge()}</Field.Label>
            <Switch id={moveResourcesId} bind:checked={moveResources} />
          </Field.Field>
          {#if moveResources}
            <p
              class="label-warning border-label-default bg-label-dimmer text-label-stronger mx-4 mb-3 rounded-md border px-2 py-1 text-sm"
            >
              <span class="font-bold">{m.hint()}:</span>
              {m.move_assistant_hint()}
            </p>
          {/if}
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        <Button type="submit" variant="destructive"
          >{isProcessing ? m.moving() : m.move_assistant()}</Button
        >
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>

<PublishingDialog
  resource={assistant}
  endpoints={eneo.assistants}
  openController={showPublishDialog}
  resourceKind="assistant"
  awaitUpdate
></PublishingDialog>
