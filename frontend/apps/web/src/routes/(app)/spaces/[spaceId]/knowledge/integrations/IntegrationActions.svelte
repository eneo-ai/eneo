<script lang="ts">
  import { type IntegrationKnowledge, type components } from "@eneo/eneo-js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { IconList } from "@eneo/icons/list";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import NameDialog from "$lib/components/NameDialog.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";

  type Props = { knowledgeItem: IntegrationKnowledge };
  let { knowledgeItem }: Props = $props();

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  async function deleteKnowledge() {
    await eneo.integrations.knowledge.delete({
      knowledge: knowledgeItem,
      space: $currentSpace
    });
    refreshCurrentSpace();
  }

  async function renameKnowledge(name: string) {
    await eneo.integrations.knowledge.rename({
      knowledge: knowledgeItem,
      space: $currentSpace,
      name
    });
    refreshCurrentSpace();
  }

  async function triggerFullSync() {
    await eneo.integrations.knowledge.triggerFullSync({
      knowledge: knowledgeItem,
      space: $currentSpace
    });
    refreshCurrentSpace();
  }

  type TabularPolicy = components["schemas"]["TabularPolicy"];
  /** The policy shown in the dialog; set from the saved one each time it opens. */
  let tabularPolicy = $state<TabularPolicy>("index_and_tool");

  function openTabularPolicyDialog() {
    tabularPolicy = knowledgeItem.tabular_policy ?? "index_and_tool";
    showTabularPolicyDialog = true;
  }

  async function saveTabularPolicy() {
    if (tabularPolicy !== (knowledgeItem.tabular_policy ?? "index_and_tool")) {
      await eneo.integrations.knowledge.update({
        knowledge: knowledgeItem,
        space: $currentSpace,
        tabular_policy: tabularPolicy
      });
      refreshCurrentSpace();
    }
  }

  let showDeleteDialog = $state(false);
  let showRenameDialog = $state(false);
  let showSyncDialog = $state(false);
  let showTabularPolicyDialog = $state(false);
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
    {#if knowledgeItem.permissions?.includes("edit")}
      <DropdownMenu.Item onSelect={() => (showRenameDialog = true)}>
        <IconEdit size="sm" />{m.rename()}
      </DropdownMenu.Item>
    {/if}
    {#if knowledgeItem.integration_type === "sharepoint" && knowledgeItem.permissions?.includes("edit")}
      <DropdownMenu.Item onSelect={openTabularPolicyDialog}>
        <IconList size="sm" />{m.integration_tabular_policy_title()}
      </DropdownMenu.Item>
      <DropdownMenu.Item onSelect={() => (showSyncDialog = true)}>
        <IconRefresh size="sm" />{m.trigger_full_sync()}
      </DropdownMenu.Item>
    {/if}
    {#if knowledgeItem.permissions?.includes("delete")}
      <DropdownMenu.Item variant="destructive" onSelect={() => (showDeleteDialog = true)}>
        <IconTrash size="sm" />{m.delete()}
      </DropdownMenu.Item>
    {/if}
  </DropdownMenu.Content>
</DropdownMenu.Root>

<NameDialog
  bind:open={showRenameDialog}
  title={m.integration_rename_title()}
  label={m.name()}
  initial={knowledgeItem.name}
  submitLabel={m.save()}
  pendingLabel={m.saving()}
  errorContext={m.integration_rename_error()}
  onSubmit={renameKnowledge}
/>

<ConfirmDialog
  bind:open={showTabularPolicyDialog}
  title={m.integration_tabular_policy_title()}
  description={m.integration_tabular_policy_description({ knowledgeName: knowledgeItem.name })}
  confirmLabel={m.save()}
  pendingLabel={m.saving()}
  errorContext={m.integration_tabular_policy_error()}
  variant="default"
  onConfirm={saveTabularPolicy}
>
  <RadioGroup.Root
    value={tabularPolicy}
    onValueChange={(value) => (tabularPolicy = value as TabularPolicy)}
    aria-label={m.integration_tabular_policy_title()}
    class="grid gap-3"
  >
    <Field.Label for="tabular-policy-index-and-tool" class="font-normal">
      <Field.Field orientation="horizontal">
        <RadioGroup.Item value="index_and_tool" id="tabular-policy-index-and-tool" />
        <span class="flex flex-col">
          <span>{m.integration_tabular_policy_index_and_tool()}</span>
          <span class="text-secondary text-sm">
            {m.integration_tabular_policy_index_and_tool_help()}
          </span>
        </span>
      </Field.Field>
    </Field.Label>
    <Field.Label for="tabular-policy-tool-only" class="font-normal">
      <Field.Field orientation="horizontal">
        <RadioGroup.Item value="tool_only" id="tabular-policy-tool-only" />
        <span class="flex flex-col">
          <span>{m.integration_tabular_policy_tool_only()}</span>
          <span class="text-secondary text-sm">
            {m.integration_tabular_policy_tool_only_help()}
          </span>
        </span>
      </Field.Field>
    </Field.Label>
  </RadioGroup.Root>
</ConfirmDialog>

<ConfirmDialog
  bind:open={showSyncDialog}
  title={m.trigger_full_sync()}
  description={m.confirm_full_sync({ knowledgeName: knowledgeItem.name })}
  confirmLabel={m.start_full_sync()}
  pendingLabel={m.syncing()}
  errorContext={m.sync_failed()}
  variant="default"
  onConfirm={triggerFullSync}
/>

<ConfirmDialog
  bind:open={showDeleteDialog}
  title={m.delete_integration_knowledge()}
  description={m.confirm_delete_integration_knowledge({ knowledgeName: knowledgeItem.name })}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.integration_delete_error()}
  onConfirm={deleteKnowledge}
/>
