<script lang="ts">
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import type { AppSparse } from "@eneo/eneo-js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import PublishingDialog from "$lib/features/publishing/components/PublishingDialog.svelte";
  import { writable } from "svelte/store";
  import { IconArrowDownToLine } from "@eneo/icons/arrow-down-to-line";
  import { IconArrowUpToLine } from "@eneo/icons/arrow-up-to-line";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let app: AppSparse;

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const eneo = getEneo();

  async function deleteService() {
    isProcessing = true;
    try {
      await eneo.apps.delete(app);
      refreshCurrentSpace();
      showDeleteDialog = false;
    } catch (e) {
      toastError(e, m.could_not_delete_app());
      console.error(e);
    }
    isProcessing = false;
  }

  let isProcessing = false;
  let showDeleteDialog = false;
  const showPublishDialog = writable(false);

  let showActions = (["edit", "publish", "delete"] as const).some((permission) =>
    app.permissions?.includes(permission)
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
      {#if app.permissions?.includes("edit")}
        <DropdownMenu.Item>
          {#snippet child({ props })}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing -->
            <a
              {...props}
              href={localizeHref(`/spaces/${$currentSpace.routeId}/apps/${app.id}/edit`)}
            >
              <IconEdit size="sm" />
              {m.edit()}
            </a>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {/snippet}
        </DropdownMenu.Item>
      {/if}
      {#if app.permissions?.includes("publish")}
        <DropdownMenu.Item
          onSelect={() => {
            $showPublishDialog = true;
          }}
        >
          {#if app.published}
            <IconArrowDownToLine size="sm"></IconArrowDownToLine>
            {m.unpublish()}
          {:else}
            <IconArrowUpToLine size="sm"></IconArrowUpToLine>
            {m.publish()}
          {/if}
        </DropdownMenu.Item>
      {/if}
      {#if app.permissions?.includes("delete")}
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
      <AlertDialog.Title>{m.delete_app()}</AlertDialog.Title>
      <AlertDialog.Description>{m.confirm_delete_app()}</AlertDialog.Description>
    </AlertDialog.Header>

    <AlertDialog.Footer class={dialogLayout.footer}>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <Button variant="destructive" onclick={deleteService}
        >{isProcessing ? m.deleting() : m.delete()}</Button
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<PublishingDialog
  resource={app}
  endpoints={eneo.apps}
  openController={showPublishDialog}
  resourceKind="app"
  awaitUpdate
></PublishingDialog>
