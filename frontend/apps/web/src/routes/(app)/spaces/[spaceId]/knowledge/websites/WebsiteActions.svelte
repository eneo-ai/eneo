<script lang="ts">
  import { type WebsiteSparse } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconMove } from "@eneo/icons/move";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import MoveToSpaceDialog from "$lib/features/spaces/components/MoveToSpaceDialog.svelte";
  import WebsiteEditor from "./WebsiteEditor.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  export let website: WebsiteSparse;

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  $: isOrgSpace = $currentSpace.organization === true;

  async function deleteWebsite() {
    await eneo.websites.delete({ id: website.id });
    refreshCurrentSpace();
  }

  async function moveWebsite(targetSpace: { id: string }) {
    await eneo.websites.transfer({ website, targetSpace });
    refreshCurrentSpace();
  }

  const showEditDialog = writable(false);
  let showDeleteDialog = false;
  let showMoveDialog = false;
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

{#snippet deleteDescription()}
  {m.confirm_delete_crawl_start()}
  <span class="italic">
    {website.name ? `${website.name} (${website.url})` : website.url}
  </span>{m.confirm_delete_crawl_end()}
{/snippet}

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_crawl()}
  description={deleteDescription}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.could_not_delete_crawl()}
  onConfirm={deleteWebsite}
/>

<WebsiteEditor mode="update" {website} showDialog={showEditDialog}></WebsiteEditor>

<MoveToSpaceDialog
  bind:open={showMoveDialog}
  title={m.move_website()}
  submitLabel={m.move_website()}
  hint={m.move_website_hint()}
  onMove={moveWebsite}
/>
