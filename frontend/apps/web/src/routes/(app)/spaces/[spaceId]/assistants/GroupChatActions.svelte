<script lang="ts">
  import type { GroupChatSparse } from "@eneo/eneo-js";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { writable } from "svelte/store";
  import PublishingDialog from "$lib/features/publishing/components/PublishingDialog.svelte";
  import { IconArrowUpToLine } from "@eneo/icons/arrow-up-to-line";
  import { IconArrowDownToLine } from "@eneo/icons/arrow-down-to-line";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let groupChat: GroupChatSparse;

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const eneo = getEneo();

  const deleteGroupChat = createAsyncState(async () => {
    try {
      await eneo.groupChats.delete(groupChat);
      refreshCurrentSpace("applications");
      showDeleteDialog = false;
    } catch (e) {
      toastError(e, m.could_not_delete_group_chat());
      console.error(e);
    }
  });

  let showDeleteDialog = false;
  const showPublishDialog = writable(false);

  let showActions = (["edit", "publish", "delete"] as const).some((permission) =>
    groupChat.permissions?.includes(permission)
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
      {#if groupChat.permissions?.includes("edit")}
        <DropdownMenu.Item>
          {#snippet child({ props })}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
            <a
              {...props}
              href={localizeHref(
                `/spaces/${$currentSpace.routeId}/group-chats/${groupChat.id}/edit`
              )}
            >
              <IconEdit size="sm" />
              {m.edit()}
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {/snippet}
        </DropdownMenu.Item>
      {/if}
      {#if groupChat.permissions?.includes("publish")}
        <DropdownMenu.Item
          onSelect={() => {
            $showPublishDialog = true;
          }}
        >
          {#if groupChat.published}
            <IconArrowDownToLine size="sm"></IconArrowDownToLine>
            {m.unpublish()}
          {:else}
            <IconArrowUpToLine size="sm"></IconArrowUpToLine>
            {m.publish()}
          {/if}
        </DropdownMenu.Item>
      {/if}
      {#if groupChat.permissions?.includes("delete")}
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
      <AlertDialog.Title>{m.delete_group_chat()}</AlertDialog.Title>
      <AlertDialog.Description
        >{m.confirm_delete_group_chat({ groupChatName: groupChat.name })}</AlertDialog.Description
      >
    </AlertDialog.Header>

    <AlertDialog.Footer class={dialogLayout.footer}>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button variant="destructive" onclick={deleteGroupChat}
        >{deleteGroupChat.isLoading ? m.deleting() : m.delete()}</Button
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<PublishingDialog
  resource={groupChat}
  endpoints={eneo.groupChats}
  openController={showPublishDialog}
  awaitUpdate
></PublishingDialog>
