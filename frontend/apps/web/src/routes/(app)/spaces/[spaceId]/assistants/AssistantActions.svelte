<script lang="ts">
  import type { AssistantSparse } from "@eneo/eneo-js";
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
  import { writable } from "svelte/store";
  import PublishingDialog from "$lib/features/publishing/components/PublishingDialog.svelte";
  import { IconArrowUpToLine } from "@eneo/icons/arrow-up-to-line";
  import { IconArrowDownToLine } from "@eneo/icons/arrow-down-to-line";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let assistant: AssistantSparse;

  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const eneo = getEneo();

  async function deleteAssistant() {
    await eneo.assistants.delete(assistant);
    refreshCurrentSpace("applications");
  }

  async function moveAssistant(
    targetSpace: { id: string },
    { moveResources }: { moveResources: boolean }
  ) {
    await eneo.assistants.transfer({ assistant, moveResources, targetSpace });
    refreshCurrentSpace();
  }

  let showDeleteDialog = false;
  let showMoveDialog = false;
  const showPublishDialog = writable(false);

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

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_assistant()}
  description={m.confirm_delete_assistant({ name: assistant.name })}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.could_not_delete_assistant()}
  onConfirm={deleteAssistant}
/>

<MoveToSpaceDialog
  bind:open={showMoveDialog}
  title={m.move_assistant()}
  submitLabel={m.move_assistant()}
  resourcesOption={{ label: m.include_assistants_knowledge(), hint: m.move_assistant_hint() }}
  onMove={moveAssistant}
/>

<PublishingDialog
  resource={assistant}
  endpoints={eneo.assistants}
  openController={showPublishDialog}
  resourceKind="assistant"
  awaitUpdate
></PublishingDialog>
