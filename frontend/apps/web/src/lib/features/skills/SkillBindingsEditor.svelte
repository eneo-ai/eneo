<script lang="ts">
  import type { SkillBindingReferenceInput, SkillBindingSummary, SkillPublic } from "@eneo/eneo-js";
  import { useId } from "bits-ui";
  import { ArrowDown, ArrowUp, Info, Plus, RefreshCw, Trash2 } from "lucide-svelte";
  import { onDestroy, tick, untrack } from "svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { m } from "$lib/paraglide/messages";
  import SkillForm from "./SkillForm.svelte";
  import SkillPreview from "./SkillPreview.svelte";
  import { skillBindingPreviewTarget } from "./skillBindingCatalog";
  import type {
    GetSkillBindingPreview,
    ListSkillBindingCatalog,
    SkillBindingCatalogPage,
    SkillBindingPreview
  } from "./skillBindingCatalog";
  import { SkillCatalogQuery } from "./skillCatalogQuery.svelte";
  import {
    appendSkillRevisionBinding,
    getAvailableSkills,
    getSkillCandidateRevisionNumber,
    getSkillBindingRows,
    mergeSkillCatalog,
    moveSkillBinding,
    removeSkillBinding,
    upgradeSkillBinding,
    type SkillBindingCandidate,
    type SkillBindingRevisionMetadata,
    type SkillBindingRow,
    type SkillFormValue
  } from "./skillBindings";

  type Props = {
    bindings: SkillBindingReferenceInput[];
    initialCatalogPage: SkillBindingCatalogPage;
    bindingSummaries: SkillBindingSummary[];
    canEditBindings: boolean;
    canCreateSkills: boolean;
    onListCatalog: ListSkillBindingCatalog;
    onGetSkillPreview: GetSkillBindingPreview;
    onCreateSkill?: (value: SkillFormValue) => Promise<SkillPublic>;
  };

  let {
    bindings = $bindable(),
    initialCatalogPage,
    bindingSummaries,
    canEditBindings,
    canCreateSkills,
    onListCatalog,
    onGetSkillPreview,
    onCreateSkill
  }: Props = $props();

  const id = useId();
  const addExistingTriggerId = `${id}-add-existing`;
  const createTriggerId = `${id}-create`;

  let addExistingOpen = $state(false);
  let createOpen = $state(false);
  let createFormDirty = $state(false);
  let createdSkills = $state<SkillBindingCandidate[]>([]);
  let previewOpen = $state(false);
  let previewCandidate = $state<SkillBindingCandidate | null>(null);
  let preview = $state<SkillBindingPreview | null>(null);
  let previewLoading = $state(false);
  let previewError = $state<string | null>(null);
  let previewRequestGeneration = 0;
  let loadedRevisionMetadata = $state<SkillBindingRevisionMetadata[]>([]);
  let upgradeLoadingSkillId = $state<string | null>(null);
  let upgradeError = $state<string | null>(null);
  let announcement = $state("");

  let loadedInitialPage = untrack(() => initialCatalogPage);
  const skillCatalog = new SkillCatalogQuery<SkillBindingCandidate>(loadedInitialPage, (params) =>
    onListCatalog(params)
  );
  onDestroy(() => skillCatalog.dispose());

  $effect(() => {
    if (initialCatalogPage === loadedInitialPage) return;
    loadedInitialPage = initialCatalogPage;
    skillCatalog.reset(initialCatalogPage);
  });

  const matchingCreatedSkills = $derived.by(() => {
    const normalizedQuery = skillCatalog.query.trim().toLocaleLowerCase();
    if (!normalizedQuery) return createdSkills;
    return createdSkills.filter((skill) =>
      `${skill.display_name} ${skill.description} ${skill.slug} ${skill.id}`
        .toLocaleLowerCase()
        .includes(normalizedQuery)
    );
  });
  const catalog = $derived(mergeSkillCatalog(skillCatalog.items, matchingCreatedSkills));
  const addExistingChoices = $derived(getAvailableSkills(catalog, bindings));
  const rows = $derived(
    getSkillBindingRows(bindings, bindingSummaries, catalog, loadedRevisionMetadata)
  );
  const emptyChoiceMessage = $derived.by(() => {
    if (skillCatalog.loading) return m.skills_search_loading();
    if (skillCatalog.query.trim()) return m.skills_search_no_results();
    if (catalog.length > 0 && addExistingChoices.length === 0) return m.skills_all_attached();
    return m.skills_no_available();
  });

  function rowName(row: SkillBindingRow): string {
    return row.displayName ?? m.skills_unknown_skill();
  }

  function focusElement(id: string) {
    void tick().then(() => document.getElementById(id)?.focus());
  }

  async function openPreview(skill: SkillBindingCandidate) {
    if (!canEditBindings) return;
    const requestGeneration = ++previewRequestGeneration;
    addExistingOpen = false;
    previewCandidate = skill;
    preview = null;
    previewError = null;
    previewOpen = true;
    previewLoading = true;
    try {
      const loaded = await onGetSkillPreview(skillBindingPreviewTarget(skill));
      if (previewRequestGeneration === requestGeneration) preview = loaded;
    } catch {
      if (previewRequestGeneration === requestGeneration) {
        previewError = m.skills_preview_load_error();
      }
    } finally {
      if (previewRequestGeneration === requestGeneration) previewLoading = false;
    }
  }

  function addPreviewedSkill() {
    if (!canEditBindings || preview === null) return;
    bindings = appendSkillRevisionBinding(bindings, {
      id: preview.id,
      revisionId: preview.revisionId
    });
    previewOpen = false;
    announcement = m.skills_added_to_draft_announcement({ name: preview.displayName });
    focusElement(addExistingTriggerId);
  }

  async function createSkill(value: SkillFormValue) {
    if (!onCreateSkill) return;
    const created = await onCreateSkill(value);
    const candidate = { ...created, source: "space" as const };
    createdSkills = [...createdSkills.filter((skill) => skill.id !== created.id), candidate];
    bindings = appendSkillRevisionBinding(bindings, {
      id: created.id,
      revisionId: created.current_revision_id
    });
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

  async function useLatestRevision(row: SkillBindingRow, index: number) {
    if (
      !canEditBindings ||
      row.attachableRevisionId === undefined ||
      row.attachableRevisionNumber === undefined ||
      row.isActive !== true ||
      row.source === undefined ||
      row.slug === undefined ||
      row.displayName === undefined ||
      row.description === undefined ||
      upgradeLoadingSkillId !== null
    )
      return;
    upgradeError = null;
    upgradeLoadingSkillId = row.reference.skill_id;
    try {
      const catalogHasAttachableRevision = catalog.some(
        (skill) =>
          skill.id === row.reference.skill_id &&
          skillBindingPreviewTarget(skill).revisionId === row.attachableRevisionId
      );
      if (!catalogHasAttachableRevision) {
        const loaded = await onGetSkillPreview({
          id: row.reference.skill_id,
          source: row.source,
          slug: row.slug,
          revisionId: row.attachableRevisionId,
          displayName: row.displayName,
          description: row.description
        });
        if (
          loaded.id !== row.reference.skill_id ||
          loaded.revisionId !== row.attachableRevisionId
        ) {
          throw new Error("Skill preview did not match the requested revision");
        }
        loadedRevisionMetadata = [
          ...loadedRevisionMetadata.filter(
            (metadata) => metadata.id !== loaded.id || metadata.revisionId !== loaded.revisionId
          ),
          loaded
        ];
      }
      const nextBindings = upgradeSkillBinding(bindings, index, {
        id: row.reference.skill_id,
        attachableRevisionId: row.attachableRevisionId,
        isActive: row.isActive
      });
      if (nextBindings === bindings) return;
      bindings = nextBindings;
      announcement = m.skills_revision_upgraded_announcement({
        name: rowName(row),
        revision: String(row.attachableRevisionNumber)
      });
      focusElement(rowId(row.reference.skill_id));
    } catch {
      upgradeError = m.skills_preview_load_error();
    } finally {
      upgradeLoadingSkillId = null;
    }
  }

  function setCreateOpen(open: boolean) {
    if (!open && createFormDirty && !confirm(m.unsaved_changes_warning())) {
      createOpen = true;
      return;
    }
    createOpen = open;
    if (!open) createFormDirty = false;
  }

  function setAddExistingOpen(open: boolean) {
    addExistingOpen = open;
    if (open) return;
    if (skillCatalog.query) skillCatalog.setQuery("");
  }

  function setPreviewOpen(open: boolean) {
    previewOpen = open;
    if (open) return;
    previewRequestGeneration += 1;
    const restorePickerFocus = previewCandidate !== null;
    previewCandidate = null;
    preview = null;
    previewError = null;
    previewLoading = false;
    if (restorePickerFocus) focusElement(addExistingTriggerId);
  }

  function retryPreview() {
    if (previewCandidate) void openPreview(previewCandidate);
  }

  function rowId(skillId: string): string {
    return `${id}-row-${skillId}`;
  }
</script>

<div class="flex flex-col gap-4">
  <div class="flex items-start justify-between gap-3">
    <p class="text-muted-foreground max-w-[65ch] text-sm leading-6">
      {m.skills_binding_draft_description()}
    </p>
    {#if rows.length > 0}
      <Badge variant="secondary" class="shrink-0">
        {m.skills_binding_count({ count: String(rows.length) })}
      </Badge>
    {/if}
  </div>

  {#if upgradeError}
    <p class="text-destructive text-sm" role="alert">{upgradeError}</p>
  {/if}

  {#if rows.length === 0}
    <p class="text-muted-foreground py-2 text-sm">{m.skills_no_bindings()}</p>
  {:else}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex (overflow region must be keyboard-scrollable) -->
    <div
      class="border-border focus-visible:ring-ring max-h-[min(32rem,60dvh)] overflow-y-auto overscroll-contain border-y outline-none focus-visible:ring-2 focus-visible:ring-offset-2 [scrollbar-gutter:stable]"
      role="region"
      aria-label={m.skills_binding_scroll_region_label({ count: String(rows.length) })}
      tabindex="0"
    >
      <ol class="divide-border divide-y" aria-label={m.skills_binding_order_label()}>
        {#each rows as row, index (row.reference.skill_id)}
          <li
            id={rowId(row.reference.skill_id)}
            tabindex="-1"
            class="focus-visible:ring-ring flex flex-col gap-3 p-3 outline-none focus-visible:ring-2 focus-visible:ring-inset sm:flex-row sm:items-start sm:justify-between"
          >
            <div class="flex min-w-0 flex-1 items-start gap-3">
              <Badge variant="outline" class="mt-0.5 min-w-7 justify-center px-1.5 tabular-nums">
                {index + 1}
              </Badge>
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium">{rowName(row)}</p>
                {#if row.description}
                  <p class="text-muted-foreground mt-1 line-clamp-2 max-w-[75ch] text-sm leading-6">
                    {row.description}
                  </p>
                {/if}
                <div class="mt-2 flex flex-wrap items-center gap-1.5">
                  {#if row.pinnedRevision !== undefined}
                    <Badge variant="outline">
                      {m.skills_revision_label({ revision: String(row.pinnedRevision) })}
                    </Badge>
                  {/if}
                  {#if row.isActive === false}
                    <Badge variant="outline">{m.skills_unavailable_status()}</Badge>
                    <span class="text-muted-foreground text-xs">
                      {m.skills_unavailable_binding_explanation()}
                    </span>
                  {/if}
                  {#if row.hasNewerRevision && row.attachableRevisionNumber !== undefined}
                    <Badge variant="secondary">
                      {m.skills_newer_revision_available({
                        revision: String(row.attachableRevisionNumber)
                      })}
                    </Badge>
                  {/if}
                </div>
              </div>
            </div>

            <div class="flex shrink-0 flex-wrap items-center gap-1 sm:justify-end">
              {#if row.hasNewerRevision && row.attachableRevisionNumber !== undefined && row.isActive}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!canEditBindings || upgradeLoadingSkillId !== null}
                  aria-label={m.skills_use_latest_revision_aria({
                    name: rowName(row),
                    revision: String(row.attachableRevisionNumber)
                  })}
                  onclick={() => void useLatestRevision(row, index)}
                >
                  <RefreshCw data-icon="inline-start" aria-hidden="true" />
                  {m.skills_use_latest_revision()}
                </Button>
              {/if}
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                class="size-11 md:size-7"
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
                class="size-11 md:size-7"
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
                class="text-muted-foreground hover:text-destructive size-11 md:size-7"
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
    </div>
  {/if}

  <div class="flex flex-wrap gap-2">
    <Popover.Root bind:open={addExistingOpen} onOpenChange={setAddExistingOpen}>
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
            <Plus data-icon="inline-start" aria-hidden="true" />
            {m.skills_add_existing()}
          </Button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content
        align="start"
        sideOffset={8}
        collisionPadding={16}
        class="w-[min(32rem,calc(100vw-2rem))] p-0"
      >
        <Command.Root
          label={m.skills_search_existing()}
          shouldFilter={false}
          class="p-0 [&_[data-slot=command-input-wrapper]]:border-border [&_[data-slot=command-input-wrapper]]:border-b [&_[data-slot=command-input-wrapper]]:p-2 [&_[data-slot=input-group]]:border-input [&_[data-slot=input-group]]:bg-background"
        >
          <Command.Input
            value={skillCatalog.query}
            placeholder={m.skills_search_existing()}
            aria-label={m.skills_search_existing()}
            oninput={(event) => skillCatalog.setQuery(event.currentTarget.value)}
          />
          <Command.List
            class="max-h-[min(24rem,55dvh)]"
            aria-label={m.skills_available_group()}
            aria-busy={skillCatalog.loading || skillCatalog.loadingMore}
          >
            {#if skillCatalog.error}
              <div class="flex flex-col items-center gap-2 px-4 py-6 text-center">
                <p class="text-destructive text-sm" role="alert">{skillCatalog.error}</p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onclick={() => skillCatalog.retry()}
                >
                  {m.retry()}
                </Button>
              </div>
            {:else if skillCatalog.loading && addExistingChoices.length === 0}
              <p class="text-muted-foreground px-4 py-6 text-center text-sm" role="status">
                {m.loading()}
              </p>
            {:else if addExistingChoices.length === 0}
              <p class="text-muted-foreground px-4 py-6 text-center text-sm">
                {emptyChoiceMessage}
              </p>
            {/if}
            {#if addExistingChoices.length > 0}
              <Command.Group heading={m.skills_available_group()}>
                {#each addExistingChoices as skill (skill.id)}
                  <Command.Item
                    value={`${skill.display_name} ${skill.description} ${skill.slug} ${skill.id}`}
                    class="data-selected:bg-accent-dimmer/40 items-start px-3 py-3 transition-colors duration-150 motion-reduce:transition-none [&_.cn-command-item-indicator]:hidden"
                    onSelect={() => openPreview(skill)}
                  >
                    <div class="min-w-0 flex-1">
                      <div class="flex items-start justify-between gap-3">
                        <p class="line-clamp-2 font-medium leading-5">{skill.display_name}</p>
                        <Badge variant="outline" class="shrink-0">
                          {m.skills_revision_label({
                            revision: String(getSkillCandidateRevisionNumber(skill))
                          })}
                        </Badge>
                      </div>
                      <p class="text-muted-foreground mt-1 line-clamp-2 text-sm leading-5">
                        {skill.description}
                      </p>
                      <div class="mt-2 flex min-w-0 flex-wrap items-center gap-1.5">
                        <Badge variant="secondary">
                          {skill.source === "organization"
                            ? m.skills_source_organization()
                            : m.skills_source_space()}
                        </Badge>
                        <span class="text-muted-foreground truncate font-mono text-xs">
                          {skill.slug}
                        </span>
                      </div>
                    </div>
                  </Command.Item>
                {/each}
              </Command.Group>
            {/if}
            {#if skillCatalog.loading && addExistingChoices.length > 0}
              <p class="text-muted-foreground px-4 py-2 text-center text-sm" role="status">
                {m.loading()}
              </p>
            {/if}
            {#if skillCatalog.hasMore && !skillCatalog.loading}
              <div class="border-border border-t p-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  class="w-full"
                  disabled={skillCatalog.loadingMore}
                  onclick={() => skillCatalog.loadMore()}
                >
                  {skillCatalog.loadingMore ? m.loading() : m.load_more()}
                </Button>
              </div>
            {/if}
          </Command.List>
        </Command.Root>
      </Popover.Content>
    </Popover.Root>

    <Dialog.Root bind:open={previewOpen} onOpenChange={setPreviewOpen}>
      <Dialog.Content
        class="grid max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-w-2xl"
        closeLabel={m.close()}
      >
        <Dialog.Header class="border-b px-6 py-5 pr-12">
          <Dialog.Title>
            {m.skills_preview_title({
              name: preview?.displayName ?? previewCandidate?.display_name ?? m.skills()
            })}
          </Dialog.Title>
          <Dialog.Description>{m.skills_preview_description()}</Dialog.Description>
        </Dialog.Header>
        <div class="min-h-0 overflow-y-auto px-6 py-5 [scrollbar-gutter:stable]">
          {#if previewLoading}
            <p class="text-muted-foreground py-8 text-center text-sm" role="status">
              {m.loading()}
            </p>
          {:else if previewError}
            <div class="flex flex-col items-center gap-3 py-8 text-center">
              <p class="text-destructive text-sm" role="alert">{previewError}</p>
              {#if previewCandidate}
                <Button type="button" variant="outline" onclick={retryPreview}>
                  {m.retry()}
                </Button>
              {/if}
            </div>
          {:else if preview}
            <SkillPreview {preview} />
          {/if}
        </div>
        <Dialog.Footer class="border-t px-6 py-4">
          <Button type="button" variant="outline" onclick={() => setPreviewOpen(false)}>
            {m.cancel()}
          </Button>
          <Button type="button" disabled={preview === null} onclick={addPreviewedSkill}>
            <Plus data-icon="inline-start" aria-hidden="true" />
            {m.skills_add_to_draft()}
          </Button>
        </Dialog.Footer>
      </Dialog.Content>
    </Dialog.Root>

    {#if canCreateSkills && onCreateSkill}
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
          class="grid max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden p-0 sm:max-w-2xl"
          closeLabel={m.close()}
        >
          <Dialog.Header class="border-b px-6 py-5 pr-12">
            <Dialog.Title>{m.skills_create_dialog_title()}</Dialog.Title>
            <Dialog.Description>{m.skills_create_dialog_description()}</Dialog.Description>
          </Dialog.Header>
          <div class="min-h-0 overflow-y-auto px-6 py-5 [scrollbar-gutter:stable]">
            <div class="flex flex-col gap-5">
              <Alert.Root role="note">
                <Info aria-hidden="true" />
                <Alert.Title>{m.skills_create_immediate_title()}</Alert.Title>
                <Alert.Description>{m.skills_create_immediate_description()}</Alert.Description>
              </Alert.Root>

              <SkillForm
                mode="create"
                onSubmit={createSkill}
                onDirtyChange={(dirty) => (createFormDirty = dirty)}
              />
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Root>
    {/if}
  </div>

  <p class="sr-only" aria-live="polite" aria-atomic="true">{announcement}</p>
</div>
