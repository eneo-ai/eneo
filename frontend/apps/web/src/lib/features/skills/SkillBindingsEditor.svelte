<script lang="ts">
  import type {
    SkillBindingReferenceInput,
    SkillBindingSummary,
    SkillPublic,
    SkillSparse
  } from "@eneo/eneo-js";
  import { useId } from "bits-ui";
  import { ArrowDown, ArrowUp, ChevronsUpDown, Info, Plus, RefreshCw, Trash2 } from "lucide-svelte";
  import { tick } from "svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { m } from "$lib/paraglide/messages";
  import SkillForm from "./SkillForm.svelte";
  import {
    appendSkillBinding,
    getAvailableSkills,
    getSkillBindingRows,
    mergeSkillCatalog,
    moveSkillBinding,
    removeSkillBinding,
    upgradeSkillBinding,
    type SkillBindingRow,
    type SkillFormValue
  } from "./skillBindings";

  type Props = {
    bindings: SkillBindingReferenceInput[];
    availableSkills: SkillSparse[];
    bindingSummaries: SkillBindingSummary[];
    canEditBindings: boolean;
    canCreateSkills: boolean;
    onCreateSkill: (value: SkillFormValue) => Promise<SkillPublic>;
  };

  let {
    bindings = $bindable(),
    availableSkills,
    bindingSummaries,
    canEditBindings,
    canCreateSkills,
    onCreateSkill
  }: Props = $props();

  const id = useId();
  const addExistingTriggerId = `${id}-add-existing`;
  const createTriggerId = `${id}-create`;

  let addExistingOpen = $state(false);
  let createOpen = $state(false);
  let createFormDirty = $state(false);
  let createdSkills = $state<SkillPublic[]>([]);
  let announcement = $state("");

  const catalog = $derived(mergeSkillCatalog(availableSkills, createdSkills));
  const addExistingChoices = $derived(getAvailableSkills(catalog, bindings));
  const rows = $derived(getSkillBindingRows(bindings, bindingSummaries, catalog));

  function rowName(row: SkillBindingRow): string {
    return row.displayName ?? m.skills_unknown_skill();
  }

  function focusElement(id: string) {
    void tick().then(() => document.getElementById(id)?.focus());
  }

  function addExisting(skill: SkillSparse) {
    if (!canEditBindings) return;
    bindings = appendSkillBinding(bindings, skill);
    addExistingOpen = false;
    announcement = m.skills_added_to_draft_announcement({ name: skill.display_name });
    focusElement(addExistingTriggerId);
  }

  async function createSkill(value: SkillFormValue) {
    const created = await onCreateSkill(value);
    createdSkills = [...createdSkills.filter((skill) => skill.id !== created.id), created];
    bindings = appendSkillBinding(bindings, created);
    createFormDirty = false;
    createOpen = false;
    announcement = m.skills_created_and_added_to_draft_announcement({
      name: created.display_name
    });
    focusElement(createTriggerId);
  }

  function move(row: SkillBindingRow, index: number, direction: "up" | "down") {
    if (!canEditBindings) return;
    bindings = moveSkillBinding(bindings, index, direction);
    announcement =
      direction === "up"
        ? m.skills_moved_up_announcement({ name: rowName(row) })
        : m.skills_moved_down_announcement({ name: rowName(row) });
  }

  function remove(row: SkillBindingRow, index: number) {
    if (!canEditBindings) return;
    const nextFocusId = rows[index + 1]?.reference.skill_id ?? rows[index - 1]?.reference.skill_id;
    bindings = removeSkillBinding(bindings, row.reference.skill_id);
    announcement = m.skills_removed_from_draft_announcement({ name: rowName(row) });
    focusElement(nextFocusId ? rowId(nextFocusId) : addExistingTriggerId);
  }

  function useLatestRevision(row: SkillBindingRow, index: number) {
    if (!canEditBindings || !row.currentSkill) return;
    bindings = upgradeSkillBinding(bindings, index, row.currentSkill);
    announcement = m.skills_revision_upgraded_announcement({
      name: rowName(row),
      revision: String(row.currentSkill.current_revision_number)
    });
    focusElement(rowId(row.reference.skill_id));
  }

  function setCreateOpen(open: boolean) {
    if (!open && createFormDirty && !confirm(m.unsaved_changes_warning())) {
      createOpen = true;
      return;
    }
    createOpen = open;
    if (!open) createFormDirty = false;
  }

  function rowId(skillId: string): string {
    return `${id}-row-${skillId}`;
  }
</script>

<div class="flex flex-col gap-4">
  <p class="text-muted-foreground text-sm">{m.skills_binding_draft_description()}</p>

  {#if rows.length === 0}
    <p class="text-muted-foreground py-2 text-sm">{m.skills_no_bindings()}</p>
  {:else}
    <ol class="flex flex-col gap-2" aria-label={m.skills_binding_order_label()}>
      {#each rows as row, index (row.reference.skill_id)}
        <li
          id={rowId(row.reference.skill_id)}
          tabindex="-1"
          class="border-border focus-visible:ring-ring flex flex-col gap-3 rounded-lg border p-3 outline-none focus-visible:ring-2 sm:flex-row sm:items-start sm:justify-between"
        >
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium">{rowName(row)}</p>
            {#if row.description}
              <p class="text-muted-foreground mt-1 text-sm leading-normal">{row.description}</p>
            {/if}
            <div class="mt-2 flex flex-wrap gap-1.5">
              {#if row.pinnedRevision !== undefined}
                <Badge variant="outline">
                  {m.skills_revision_label({ revision: String(row.pinnedRevision) })}
                </Badge>
              {/if}
              {#if row.isActive === false}
                <Badge variant="outline">{m.skills_inactive_status()}</Badge>
                <span class="text-muted-foreground text-xs">
                  {m.skills_inactive_binding_explanation()}
                </span>
              {/if}
              {#if row.hasNewerRevision && row.currentSkill}
                <Badge variant="secondary">
                  {m.skills_newer_revision_available({
                    revision: String(row.currentSkill.current_revision_number)
                  })}
                </Badge>
              {/if}
            </div>
          </div>

          <div class="flex shrink-0 flex-wrap items-center gap-1 sm:justify-end">
            {#if row.hasNewerRevision && row.currentSkill?.is_active}
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!canEditBindings}
                aria-label={m.skills_use_latest_revision_aria({
                  name: rowName(row),
                  revision: String(row.currentSkill.current_revision_number)
                })}
                onclick={() => useLatestRevision(row, index)}
              >
                <RefreshCw data-icon="inline-start" aria-hidden="true" />
                {m.skills_use_latest_revision()}
              </Button>
            {/if}
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              disabled={!canEditBindings || index === 0}
              aria-label={m.skills_move_up_aria({ name: rowName(row) })}
              title={m.skills_move_up_aria({ name: rowName(row) })}
              onclick={() => move(row, index, "up")}
            >
              <ArrowUp aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              disabled={!canEditBindings || index === rows.length - 1}
              aria-label={m.skills_move_down_aria({ name: rowName(row) })}
              title={m.skills_move_down_aria({ name: rowName(row) })}
              onclick={() => move(row, index, "down")}
            >
              <ArrowDown aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              disabled={!canEditBindings}
              aria-label={m.skills_remove_aria({ name: rowName(row) })}
              title={m.skills_remove_aria({ name: rowName(row) })}
              onclick={() => remove(row, index)}
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </div>
        </li>
      {/each}
    </ol>
  {/if}

  <div class="flex flex-wrap gap-2">
    <Popover.Root bind:open={addExistingOpen}>
      <Popover.Trigger>
        {#snippet child({ props })}
          <Button
            {...props}
            id={addExistingTriggerId}
            type="button"
            disabled={!canEditBindings}
            role="combobox"
            aria-label={m.skills_add_existing()}
            aria-expanded={addExistingOpen}
          >
            <ChevronsUpDown data-icon="inline-start" aria-hidden="true" />
            {m.skills_add_existing()}
          </Button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content
        align="start"
        class="w-(--bits-popover-anchor-width) min-w-[min(20rem,calc(100vw-2rem))] p-0"
      >
        <Command.Root label={m.skills_search_existing()}>
          <Command.Input
            placeholder={m.skills_search_existing()}
            aria-label={m.skills_search_existing()}
          />
          <Command.List aria-label={m.skills_available_group()}>
            <Command.Empty>{m.skills_no_available()}</Command.Empty>
            {#if addExistingChoices.length > 0}
              <Command.Group heading={m.skills_available_group()}>
                {#each addExistingChoices as skill (skill.id)}
                  <Command.Item
                    value={`${skill.display_name} ${skill.description} ${skill.slug} ${skill.id}`}
                    onSelect={() => addExisting(skill)}
                  >
                    <div class="min-w-0 flex-1">
                      <p class="truncate font-medium">{skill.display_name}</p>
                      <p class="text-muted-foreground truncate text-xs">{skill.description}</p>
                    </div>
                    <span class="text-muted-foreground shrink-0 text-xs">
                      {m.skills_revision_label({
                        revision: String(skill.current_revision_number)
                      })}
                    </span>
                  </Command.Item>
                {/each}
              </Command.Group>
            {/if}
          </Command.List>
        </Command.Root>
      </Popover.Content>
    </Popover.Root>

    <Dialog.Root bind:open={createOpen} onOpenChange={setCreateOpen}>
      <Dialog.Trigger>
        {#snippet child({ props })}
          <Button
            {...props}
            id={createTriggerId}
            type="button"
            variant="outline"
            disabled={!canEditBindings || !canCreateSkills}
          >
            <Plus data-icon="inline-start" aria-hidden="true" />
            {m.skills_create_new()}
          </Button>
        {/snippet}
      </Dialog.Trigger>
      <Dialog.Content
        class="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl"
        closeLabel={m.close()}
      >
        <Dialog.Header>
          <Dialog.Title>{m.skills_create_dialog_title()}</Dialog.Title>
          <Dialog.Description>{m.skills_create_dialog_description()}</Dialog.Description>
        </Dialog.Header>

        <Alert.Root>
          <Info aria-hidden="true" />
          <Alert.Title>{m.skills_create_immediate_title()}</Alert.Title>
          <Alert.Description>{m.skills_create_immediate_description()}</Alert.Description>
        </Alert.Root>

        <SkillForm
          mode="create"
          onSubmit={createSkill}
          onDirtyChange={(dirty) => (createFormDirty = dirty)}
        />
      </Dialog.Content>
    </Dialog.Root>
  </div>

  <p class="sr-only" aria-live="polite" aria-atomic="true">{announcement}</p>
</div>
