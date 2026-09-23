<script lang="ts">
  import { type WebsiteSparse } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconMove } from "@eneo/icons/move";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { useId } from "bits-ui";
  import WebsiteEditor from "./WebsiteEditor.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { derived, writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  export let website: WebsiteSparse;

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace, accessibleSpaces }
  } = getSpacesManager();

  $: isOrgSpace = $currentSpace.organization === true;

  async function deleteWebsite() {
    isProcessing = true;
    try {
      await eneo.websites.delete({ id: website.id });
      refreshCurrentSpace();
      showDeleteDialog = false;
    } catch (e) {
      toastError(e, m.could_not_delete_crawl());
      console.error(e);
    }
    isProcessing = false;
  }

  async function moveCollection() {
    if (!moveDestination) return;
    isProcessing = true;
    try {
      await eneo.websites.transfer({ website, targetSpace: moveDestination });
      refreshCurrentSpace();
      showMoveDialog = false;
    } catch (e) {
      toastError(e);
      console.error(e);
    }
    isProcessing = false;
  }

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

  let isProcessing = false;
  const showEditDialog = writable(false);
  let showDeleteDialog = false;
  let showMoveDialog = false;
  const destinationId = useId();
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
        <IconEllipsis />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end">
    <DropdownMenu.Item onSelect={() => ($showEditDialog = true)}>
      <IconEdit size="sm" />
      {m.edit()}
    </DropdownMenu.Item>
    {#if website.permissions?.includes("delete")}
      {#if !isOrgSpace}
        <DropdownMenu.Item onSelect={() => (showMoveDialog = true)}>
          <IconMove size="sm" />{m.move()}
        </DropdownMenu.Item>
      {/if}
      <DropdownMenu.Item variant="destructive" onSelect={() => (showDeleteDialog = true)}>
        <IconTrash size="sm" />{m.delete()}
      </DropdownMenu.Item>
    {/if}
  </DropdownMenu.Content>
</DropdownMenu.Root>

<AlertDialog.Root bind:open={showDeleteDialog}>
  <AlertDialog.Content class={dialogLayout.content()}>
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title>{m.delete_crawl()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.confirm_delete_crawl_start()}
        <span class="italic">
          {website.name ? `${website.name} (${website.url})` : website.url}
        </span>{m.confirm_delete_crawl_end()}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer class={dialogLayout.footer}>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button variant="destructive" onclick={deleteWebsite}
        >{isProcessing ? m.deleting() : m.delete()}</Button
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<WebsiteEditor mode="update" {website} showDialog={showEditDialog}></WebsiteEditor>

<Dialog.Root bind:open={showMoveDialog}>
  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        moveCollection();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.move_website()}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <Field.Field class="border-default hover:bg-hover-dimmer rounded-t-md px-4 pt-4">
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
          <p
            class="label-warning border-label-default bg-label-dimmer text-label-stronger mx-4 mt-1.5 mb-4 rounded-md border px-2 py-1 text-sm"
          >
            <span class="font-bold">{m.hint()}:</span>
            {m.move_website_hint()}
          </p>
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        <Button type="submit" variant="destructive"
          >{isProcessing ? m.moving() : m.move_website()}</Button
        >
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
