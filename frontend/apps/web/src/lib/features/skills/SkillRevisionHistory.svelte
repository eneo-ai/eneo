<script lang="ts">
  import type {
    SkillRevisionPublic,
    SkillRevisionRestorePublic,
    SkillRevisionSummaryPage,
    SkillRevisionSummaryPublic
  } from "@eneo/eneo-js";
  import Eye from "lucide-svelte/icons/eye";
  import LoaderCircle from "lucide-svelte/icons/loader-circle";
  import RotateCcw from "lucide-svelte/icons/rotate-ccw";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { tick, untrack } from "svelte";

  type Props = {
    currentRevision: SkillRevisionPublic;
    initialPage: SkillRevisionSummaryPage;
    canRestore: boolean;
    hasUnsavedChanges: boolean;
    onLoadMore: (cursor: string) => Promise<SkillRevisionSummaryPage>;
    onView: (revisionId: string) => Promise<SkillRevisionPublic>;
    onRestore: (
      revisionId: string,
      reviewedCurrentRevisionId: string
    ) => Promise<SkillRevisionRestorePublic>;
    onLoadCurrent: () => Promise<SkillRevisionPublic>;
    onAnnounce?: (message: string) => Promise<void> | void;
    onRestored?: (outcome: SkillRevisionRestorePublic) => Promise<void>;
  };

  type ComparableRevisionField = "display_name" | "description" | "instructions";

  let {
    currentRevision,
    initialPage,
    canRestore,
    hasUnsavedChanges,
    onLoadMore,
    onView,
    onRestore,
    onLoadCurrent,
    onAnnounce,
    onRestored
  }: Props = $props();

  let revisions = $state(untrack(() => [...initialPage.items]));
  let comparisonCurrentRevision = $state(untrack(() => currentRevision));
  let nextCursor = $state(untrack(() => initialPage.next_cursor ?? null));
  let loadingMore = $state(false);
  let loadError = $state<string | null>(null);
  let viewingRevisionId = $state<string | null>(null);
  let previewError = $state<string | null>(null);
  let viewedRevision = $state<SkillRevisionPublic | null>(null);
  let restoreTarget = $state<SkillRevisionPublic | null>(null);
  let restoring = $state(false);
  let restoreError = $state<string | null>(null);
  let viewFocusReturnId: string | null = null;
  let restoreSucceeded = false;

  function viewTriggerId(revisionId: string): string {
    return `skill-revision-view-${revisionId}`;
  }

  async function focusViewTrigger() {
    const triggerId = viewFocusReturnId;
    if (triggerId === null) return;
    await tick();
    document.getElementById(triggerId)?.focus();
    if (viewFocusReturnId === triggerId) viewFocusReturnId = null;
  }

  function formatCreatedAt(value: string): string {
    return new Date(value).toLocaleString(getLocale() === "sv" ? "sv-SE" : "en-US", {
      dateStyle: "short",
      timeStyle: "short"
    });
  }

  function requestRestore(revision: SkillRevisionPublic) {
    viewedRevision = null;
    restoreError = null;
    restoreTarget = revision;
  }

  function setRestoreOpen(open: boolean) {
    if (open || restoring) return;
    restoreTarget = null;
    restoreError = null;
  }

  function handleRestoreCloseAutoFocus(event: Event) {
    event.preventDefault();
    if (!restoreSucceeded && viewedRevision === null) void focusViewTrigger();
  }

  function handlePreviewCloseAutoFocus(event: Event) {
    if (restoreTarget !== null) event.preventDefault();
  }

  function isConflict(error: unknown): error is { status: number } {
    return typeof error === "object" && error !== null && "status" in error && error.status === 409;
  }

  function asSummary(revision: SkillRevisionPublic): SkillRevisionSummaryPublic {
    return {
      id: revision.id,
      skill_id: revision.skill_id,
      revision_number: revision.revision_number,
      display_name: revision.display_name,
      created_at: revision.created_at
    };
  }

  async function viewRevision(revision: SkillRevisionSummaryPublic, triggerId: string) {
    if (viewingRevisionId !== null) return;
    viewFocusReturnId = triggerId;
    previewError = null;
    if (revision.id === comparisonCurrentRevision.id) {
      viewedRevision = comparisonCurrentRevision;
      return;
    }
    viewingRevisionId = revision.id;
    try {
      viewedRevision = await onView(revision.id);
    } catch (error) {
      previewError = getErrorMessage(error, m.skills_library_preview_error());
    } finally {
      viewingRevisionId = null;
    }
  }

  async function loadOlder() {
    if (nextCursor === null || loadingMore) return;
    const cursor = nextCursor;
    loadingMore = true;
    loadError = null;
    try {
      const page = await onLoadMore(cursor);
      revisions = [...revisions, ...page.items];
      nextCursor = page.next_cursor ?? null;
    } catch (error) {
      loadError = getErrorMessage(error, m.skills_library_load_older_error());
    } finally {
      loadingMore = false;
    }
  }

  async function performRestore() {
    if (!restoreTarget || restoring) return;
    const source = restoreTarget;
    restoring = true;
    restoreError = null;
    let outcome: SkillRevisionRestorePublic;
    try {
      outcome = await onRestore(source.id, comparisonCurrentRevision.id);
    } catch (error) {
      // The alert title already says the restore failed, so this line
      // carries the cause rather than repeating it.
      restoreError = getErrorMessage(error);
      if (isConflict(error)) {
        try {
          const latest = await onLoadCurrent();
          comparisonCurrentRevision = latest;
          revisions = [
            asSummary(latest),
            ...revisions.filter((revision) => revision.id !== latest.id)
          ];
          restoreTarget = null;
          viewedRevision = source;
        } catch (refreshError) {
          restoreError = getErrorMessage(refreshError, m.skills_library_restore_refresh_error());
        }
      }
      restoring = false;
      return;
    }

    const message = outcome.created
      ? m.skills_library_restore_success({
          sourceRevision: String(outcome.restored_from_revision_number),
          newRevision: String(outcome.revision.revision_number)
        })
      : m.skills_library_restore_noop();
    await onAnnounce?.(message);
    restoreTarget = null;
    restoring = false;
    restoreSucceeded = true;
    await tick();
    if (outcome.created || outcome.revision.id !== comparisonCurrentRevision.id) {
      try {
        await onRestored?.(outcome);
      } catch {
        loadError = m.skills_library_restore_refresh_error();
      }
    }
    await focusViewTrigger();
    restoreSucceeded = false;
  }

  function revisionTitle(revision: SkillRevisionPublic | SkillRevisionSummaryPublic): string {
    return m.skills_revision_label({ revision: String(revision.revision_number) });
  }

  function fieldChanged(
    revision: SkillRevisionPublic,
    comparison: SkillRevisionPublic | null,
    field: ComparableRevisionField
  ): boolean {
    return comparison !== null && revision[field] !== comparison[field];
  }
</script>

{#snippet revisionPreview(
  revision: SkillRevisionPublic,
  comparison: SkillRevisionPublic | null,
  isCurrent = false
)}
  <section class="min-w-0">
    <header class="mb-5">
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="text-base font-semibold">{revisionTitle(revision)}</h3>
        {#if isCurrent}
          <Badge variant="secondary">{m.skills_library_current_revision()}</Badge>
        {/if}
      </div>
      <p class="text-muted-foreground mt-1 text-sm">{formatCreatedAt(revision.created_at)}</p>
    </header>
    <dl class="flex flex-col gap-4">
      <div class="flex flex-col gap-1">
        <dt
          class="text-muted-foreground flex items-baseline justify-between gap-3 text-xs font-medium"
        >
          {m.name()}
          {#if fieldChanged(revision, comparison, "display_name")}
            <span class="text-accent-stronger font-normal">{m.skills_library_changed_field()}</span>
          {/if}
        </dt>
        <dd class="text-sm">{revision.display_name}</dd>
      </div>
      <div class="flex flex-col gap-1">
        <dt
          class="text-muted-foreground flex items-baseline justify-between gap-3 text-xs font-medium"
        >
          {m.description()}
          {#if fieldChanged(revision, comparison, "description")}
            <span class="text-accent-stronger font-normal">{m.skills_library_changed_field()}</span>
          {/if}
        </dt>
        <dd class="text-sm">{revision.description}</dd>
      </div>
      <div class="flex flex-col gap-1">
        <dt
          class="text-muted-foreground flex items-baseline justify-between gap-3 text-xs font-medium"
        >
          <span>{m.skills_instructions_label()}</span>
          {#if fieldChanged(revision, comparison, "instructions")}
            <span class="text-accent-stronger font-normal">{m.skills_library_changed_field()}</span>
          {/if}
        </dt>
        <dd class="text-sm break-words whitespace-pre-wrap">
          {revision.instructions}
        </dd>
      </div>
    </dl>
  </section>
{/snippet}

<div class="border-border @container border-y">
  <Table.Root class="w-full table-fixed">
    <Table.Header>
      <Table.Row>
        <Table.Head class="w-auto @lg:w-[45%] @3xl:w-[30%]">
          {m.skills_library_revision_column()}
        </Table.Head>
        <Table.Head class="hidden @lg:table-cell">{m.name()}</Table.Head>
        <Table.Head class="hidden w-48 @3xl:table-cell">
          {m.skills_library_created_column()}
        </Table.Head>
        <Table.Head class="w-16 text-right">{m.actions()}</Table.Head>
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each revisions as revision (revision.id)}
        {@const isCurrent = revision.id === comparisonCurrentRevision.id}
        <Table.Row>
          <Table.Cell>
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium">
                {m.skills_revision_label({ revision: String(revision.revision_number) })}
              </span>
              {#if isCurrent}
                <Badge variant="secondary">{m.skills_library_current_revision()}</Badge>
              {/if}
            </div>
            <p class="text-foreground mt-1 line-clamp-2 break-words @lg:hidden">
              {revision.display_name}
            </p>
            <p class="text-muted-foreground mt-1 text-xs @3xl:hidden">
              {formatCreatedAt(revision.created_at)}
            </p>
          </Table.Cell>
          <Table.Cell class="hidden break-words whitespace-normal @lg:table-cell">
            {revision.display_name}
          </Table.Cell>
          <Table.Cell class="text-muted-foreground hidden text-sm @3xl:table-cell">
            {formatCreatedAt(revision.created_at)}
          </Table.Cell>
          <Table.Cell class="text-right">
            <div class="flex items-center justify-end gap-1">
              <Button
                id={viewTriggerId(revision.id)}
                variant="ghost"
                size="icon-sm"
                class="size-11 md:size-7"
                disabled={viewingRevisionId !== null}
                title={m.view()}
                aria-label={m.skills_library_view_revision_aria({
                  revision: String(revision.revision_number)
                })}
                onclick={() => void viewRevision(revision, viewTriggerId(revision.id))}
              >
                {#if viewingRevisionId === revision.id}
                  <LoaderCircle class="animate-spin" aria-hidden="true" />
                {:else}
                  <Eye aria-hidden="true" />
                {/if}
              </Button>
            </div>
          </Table.Cell>
        </Table.Row>
      {/each}
    </Table.Body>
  </Table.Root>
  {#if nextCursor !== null || loadError || previewError}
    <div class="border-border flex flex-col items-center gap-3 border-t px-6 py-4">
      {#if loadError}
        <p class="text-destructive text-sm" role="alert">{loadError}</p>
      {/if}
      {#if previewError}
        <p class="text-destructive text-sm" role="alert">{previewError}</p>
      {/if}
      {#if nextCursor !== null}
        <Button variant="outline" disabled={loadingMore} onclick={loadOlder}>
          {#if loadingMore}
            <LoaderCircle class="animate-spin" aria-hidden="true" />
            {m.skills_library_loading_older()}
          {:else}
            {m.skills_library_load_older()}
          {/if}
        </Button>
      {/if}
    </div>
  {/if}
</div>

<Dialog.Root
  open={viewedRevision !== null}
  onOpenChange={(open) => !open && (viewedRevision = null)}
>
  <Dialog.Content
    class="grid max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-w-2xl has-[.skill-revision-comparison]:sm:max-w-4xl"
    closeLabel={m.close()}
    onCloseAutoFocus={handlePreviewCloseAutoFocus}
  >
    <Dialog.Header class="border-b px-6 py-5 pr-12">
      <Dialog.Title>
        {viewedRevision?.id === comparisonCurrentRevision.id
          ? m.skills_library_view_revision_title({
              revision: String(viewedRevision.revision_number)
            })
          : m.skills_library_compare_revision_title({
              revision: String(viewedRevision?.revision_number ?? "")
            })}
      </Dialog.Title>
      {#if viewedRevision?.id !== comparisonCurrentRevision.id}
        <Dialog.Description>{m.skills_library_compare_revision_description()}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <div class="min-h-0 overflow-y-auto [scrollbar-gutter:stable]">
      {#if restoreError}
        <div class="flex flex-col gap-3 px-6 pt-6">
          <Alert.Root variant="destructive">
            <Alert.Title>{m.skills_library_restore_error()}</Alert.Title>
            <Alert.Description>{restoreError}</Alert.Description>
          </Alert.Root>
          {#if hasUnsavedChanges}
            <Alert.Root>
              <Alert.Title>{m.skills_library_restore_unsaved_title()}</Alert.Title>
              <Alert.Description>{m.skills_library_restore_unsaved_warning()}</Alert.Description>
            </Alert.Root>
          {/if}
        </div>
      {/if}
      {#if viewedRevision}
        {#if viewedRevision.id === comparisonCurrentRevision.id}
          <div class="p-6">{@render revisionPreview(viewedRevision, null, true)}</div>
        {:else}
          <div
            class="skill-revision-comparison divide-border grid divide-y md:grid-cols-2 md:divide-x md:divide-y-0"
          >
            <div class="p-6">
              {@render revisionPreview(viewedRevision, comparisonCurrentRevision)}
            </div>
            <div class="p-6">
              {@render revisionPreview(comparisonCurrentRevision, null, true)}
            </div>
          </div>
        {/if}
      {/if}
    </div>
    <Dialog.Footer class="mx-0 mb-0 border-t px-6 py-4">
      {#if canRestore && viewedRevision && viewedRevision.id !== comparisonCurrentRevision.id}
        <Button variant="outline" onclick={() => viewedRevision && requestRestore(viewedRevision)}>
          <RotateCcw aria-hidden="true" />
          {m.skills_library_restore_revision_from_preview()}
        </Button>
      {/if}
      <Button onclick={() => (viewedRevision = null)}>{m.close()}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<AlertDialog.Root open={restoreTarget !== null} onOpenChange={setRestoreOpen}>
  <AlertDialog.Content onCloseAutoFocus={handleRestoreCloseAutoFocus}>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {m.skills_library_restore_title({
          revision: String(restoreTarget?.revision_number ?? "")
        })}
      </AlertDialog.Title>
      <AlertDialog.Description>
        {m.skills_library_restore_description({
          revision: String(restoreTarget?.revision_number ?? "")
        })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    {#if hasUnsavedChanges}
      <Alert.Root>
        <Alert.Title>{m.skills_library_restore_unsaved_title()}</Alert.Title>
        <Alert.Description>{m.skills_library_restore_unsaved_warning()}</Alert.Description>
      </Alert.Root>
    {/if}
    {#if restoreError}
      <Alert.Root variant="destructive">
        <Alert.Title>{m.skills_library_restore_error()}</Alert.Title>
        <Alert.Description>{restoreError}</Alert.Description>
      </Alert.Root>
    {/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={restoring}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        disabled={restoring}
        onclick={(event) => {
          event.preventDefault();
          void performRestore();
        }}
      >
        {#if restoring}
          <LoaderCircle class="animate-spin" aria-hidden="true" />
          {m.skills_library_restoring()}
        {:else}
          <RotateCcw aria-hidden="true" />
          {m.skills_library_restore_action()}
        {/if}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
