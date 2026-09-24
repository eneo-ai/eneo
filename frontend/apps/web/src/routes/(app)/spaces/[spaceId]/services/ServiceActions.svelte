<script lang="ts">
  import type { ServiceSparse } from "@eneo/eneo-js";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconMove } from "@eneo/icons/move";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import MoveToSpaceDialog from "$lib/features/spaces/components/MoveToSpaceDialog.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let service: ServiceSparse;

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const eneo = getEneo();
  async function deleteService() {
    await eneo.services.delete(service);
    refreshCurrentSpace();
  }

  async function moveService(targetSpace: { id: string }) {
    await eneo.services.transfer({
      service,
      moveResources: false,
      targetSpace
    });
    refreshCurrentSpace();
  }

  let showDeleteDialog = false;
  let showMoveDialog = false;

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

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_service()}
  description={m.confirm_delete_service({ serviceName: service.name })}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.could_not_delete_service()}
  onConfirm={deleteService}
/>

<MoveToSpaceDialog
  bind:open={showMoveDialog}
  title={m.move_service()}
  submitLabel={m.move_service()}
  onMove={moveService}
/>
