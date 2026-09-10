<script lang="ts">
  import { type WebsiteSparse } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconMove } from "@eneo/icons/move";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button, Dialog, Dropdown, Select } from "@eneo/ui";
  import WebsiteEditor from "./WebsiteEditor.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { derived } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { toast } from "$lib/components/toast";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";

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
      const result = await eneo.websites.bulkDelete({ website_ids: [website.id] });
      showDeleteDialog = false;

      if (result.deleted === 1) {
        toast.success(m.websites_removed({ count: 1 }));
      } else if (result.errors.some((error) => error.error === "crawl_stop_requested")) {
        toast.info(m.website_remove_stopping());
      } else if (result.errors.some((error) => error.error === "crawl_cleanup_pending")) {
        toast.info(m.website_remove_cleanup_pending());
      } else if (result.not_found === 1) {
        toast.info(m.websites_already_removed());
      } else {
        toast.error(m.bulk_website_remove_failed());
      }
      await refreshCurrentSpace("knowledge");
    } catch (e) {
      toastError(e, m.bulk_website_remove_failed());
      console.error(e);
    } finally {
      isProcessing = false;
    }
  }

  async function moveCollection() {
    if (!moveDestination) return;
    isProcessing = true;
    try {
      await eneo.websites.transfer({ website, targetSpace: moveDestination });
      refreshCurrentSpace();
      $showMoveDialog = false;
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
  let showEditDialog = false;
  let showDeleteDialog = false;
  let showMoveDialog: Dialog.OpenState;
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button is={trigger} padding="icon" aria-label={m.actions()}>
      <IconEllipsis />
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <Button
      is={item}
      on:click={() => {
        showEditDialog = true;
      }}
      padding="icon-leading"
    >
      <IconEdit size="sm" />
      {m.edit()}</Button
    >
    {#if website.permissions?.includes("delete")}
      {#if !isOrgSpace}
        <Button
          is={item}
          on:click={() => {
            $showMoveDialog = true;
          }}
          padding="icon-leading"
        >
          <IconMove size="sm" />{m.move()}</Button
        >
      {/if}
      <Button
        is={item}
        variant="destructive"
        on:click={() => {
          showDeleteDialog = true;
        }}
        padding="icon-leading"
      >
        <IconTrash size="sm" />{m.delete()}</Button
      >
    {/if}
  </Dropdown.Menu>
</Dropdown.Root>

<AlertDialog.Root bind:open={showDeleteDialog}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.remove_website_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.remove_website_description()}
      </AlertDialog.Description>
      <p class="text-foreground text-sm font-medium break-all">
        {website.name ? `${website.name} (${website.url})` : website.url}
      </p>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={isProcessing}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={isProcessing} onclick={deleteWebsite}>
        {isProcessing ? m.deleting() : m.remove_website_confirm()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<WebsiteEditor mode="update" {website} bind:showDialog={showEditDialog}></WebsiteEditor>

<Dialog.Root bind:isOpen={showMoveDialog}>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.move_website()}</Dialog.Title>

    <Dialog.Section scrollable={false}>
      <Select.Simple
        required
        options={$moveTargets}
        bind:value={moveDestination}
        fitViewport={true}
        class="border-default hover:bg-hover-dimmer rounded-t-md px-4 pt-4"
        >{m.destination()}</Select.Simple
      >
      <p
        class="label-warning border-label-default bg-label-dimmer text-label-stronger mx-4 mt-1.5 mb-4 rounded-md border px-2 py-1 text-sm"
      >
        <span class="font-bold">{m.hint()}:</span>
        {m.move_website_hint()}
      </p>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={moveCollection}
        >{isProcessing ? m.moving() : m.move_website()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
