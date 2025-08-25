<script lang="ts">
  import { type WebsiteSparse } from "@intric/intric-js";
  import { IconEllipsis } from "@intric/icons/ellipsis";
  import { IconEdit } from "@intric/icons/edit";
  import { IconMove } from "@intric/icons/move";
  import { IconTrash } from "@intric/icons/trash";
  import { Button, Dialog, Dropdown, Select } from "@intric/ui";
  import WebsiteEditor from "./WebsiteEditor.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getIntric } from "$lib/core/Intric";
  import { derived } from "svelte/store";

  export let website: WebsiteSparse;

  const intric = getIntric();
  const {
    refreshCurrentSpace,
    state: { currentSpace, accessibleSpaces }
  } = getSpacesManager();

  $: isOrgSpace = $currentSpace.organization === true;
  
  async function deleteWebsite() {
    isProcessing = true;
    try {
      await intric.websites.delete({ id: website.id });
      refreshCurrentSpace();
      $showDeleteDialog = false;
    } catch (e) {
      alert("Could not delete crawl.");
      console.error(e);
    }
    isProcessing = false;
  }

  async function moveCollection() {
    if (!moveDestination) return;
    isProcessing = true;
    try {
      await intric.websites.transfer({ website, targetSpace: moveDestination });
      refreshCurrentSpace();
      $showMoveDialog = false;
    } catch (e) {
      alert(e);
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
  let showEditDialog: Dialog.OpenState;
  let showDeleteDialog: Dialog.OpenState;
  let showMoveDialog: Dialog.OpenState;
</script>

<Dropdown.Root>
  <Dropdown.Trigger let:trigger asFragment>
    <Button is={trigger} padding="icon">
      <IconEllipsis />
    </Button>
  </Dropdown.Trigger>
  <Dropdown.Menu let:item>
    <Button
      is={item}
      on:click={() => {
        $showEditDialog = true;
      }}
      padding="icon-leading"
    >
      <IconEdit size="sm" />
      Edit</Button
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
          <IconMove size="sm" />Move</Button
        >
      {/if}
      <Button
        is={item}
        variant="destructive"
        on:click={() => {
          $showDeleteDialog = true;
        }}
        padding="icon-leading"
      >
        <IconTrash size="sm" />Delete</Button
      >
    {/if}
  </Dropdown.Menu>
</Dropdown.Root>

<Dialog.Root alert bind:isOpen={showDeleteDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>Delete crawl</Dialog.Title>
    <Dialog.Description>
      Do you really want to delete
      <span class="italic">
        {website.name ? `${website.name} (${website.url})` : website.url}
      </span>?
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>Cancel</Button>
      <Button variant="destructive" on:click={deleteWebsite}
        >{isProcessing ? "Deleting..." : "Delete"}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<WebsiteEditor mode="update" {website} bind:showDialog={showEditDialog}></WebsiteEditor>

<Dialog.Root bind:isOpen={showMoveDialog}>
  <Dialog.Content width="medium" form>
    <Dialog.Title>Move website</Dialog.Title>

    <Dialog.Section scrollable={false}>
      <Select.Simple
        required
        options={$moveTargets}
        bind:value={moveDestination}
        fitViewport={true}
        class="border-default hover:bg-hover-dimmer rounded-t-md px-4 pt-4"
        >Destination</Select.Simple
      >
      <p
        class="label-warning border-label-default bg-label-dimmer text-label-stronger mx-4 mt-1.5 mb-4 rounded-md border px-2 py-1 text-sm"
      >
        <span class="font-bold">Hint:</span>
        The assistants in this space will no longer have access to this website.
      </p>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>Cancel</Button>
      <Button variant="destructive" on:click={moveCollection}
        >{isProcessing ? "Moving..." : "Move website"}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
