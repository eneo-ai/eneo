<script lang="ts">
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconTrash } from "@eneo/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import type { AppSparse } from "@eneo/eneo-js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import PublishingDialog from "$lib/features/publishing/components/PublishingDialog.svelte";
  import { writable } from "svelte/store";
  import { IconArrowDownToLine } from "@eneo/icons/arrow-down-to-line";
  import { IconArrowUpToLine } from "@eneo/icons/arrow-up-to-line";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let app: AppSparse;

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const eneo = getEneo();

  async function deleteApp() {
    await eneo.apps.delete(app);
    refreshCurrentSpace();
  }

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

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_app()}
  description={m.confirm_delete_app()}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.could_not_delete_app()}
  onConfirm={deleteApp}
/>

<PublishingDialog
  resource={app}
  endpoints={eneo.apps}
  openController={showPublishDialog}
  resourceKind="app"
  awaitUpdate
></PublishingDialog>
