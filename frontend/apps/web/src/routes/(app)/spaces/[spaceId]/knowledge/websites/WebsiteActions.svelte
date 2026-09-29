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
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";

  export let website: WebsiteSparse;

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  $: isOrgSpace = $currentSpace.organization === true;

  async function deleteWebsite() {
    const result = await eneo.websites.bulkDelete({ website_ids: [website.id] });

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
  }

  async function moveWebsite(targetSpace: { id: string }) {
    await eneo.websites.transfer({ website, targetSpace });
    refreshCurrentSpace();
  }

  let showEditDialog = false;
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
    <DropdownMenu.Item onSelect={() => (showEditDialog = true)}>
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

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.remove_website_title()}
  description={m.remove_website_description()}
  confirmLabel={m.remove_website_confirm()}
  pendingLabel={m.deleting()}
  errorContext={m.bulk_website_remove_failed()}
  onConfirm={deleteWebsite}
>
  <p class="text-foreground text-sm font-medium break-all">
    {website.name ? `${website.name} (${website.url})` : website.url}
  </p>
</ConfirmDialog>

<WebsiteEditor mode="update" {website} bind:showDialog={showEditDialog}></WebsiteEditor>

<MoveToSpaceDialog
  bind:open={showMoveDialog}
  title={m.move_website()}
  submitLabel={m.move_website()}
  hint={m.move_website_hint()}
  onMove={moveWebsite}
/>
