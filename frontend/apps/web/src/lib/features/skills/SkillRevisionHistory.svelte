<script lang="ts">
  import type {
    SkillRevisionPublic,
    SkillRevisionRestorePublic,
    SkillRevisionSummaryPage,
    SkillRevisionSummaryPublic
  } from "@eneo/eneo-js";
  import { Eye, LoaderCircle, RotateCcw } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
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
    onRestore: (revisionId: string) => Promise<SkillRevisionRestorePublic>;
    onAnnounce?: (message: string) => Promise<void> | void;
    onRestored?: (outcome: SkillRevisionRestorePublic) => Promise<void>;
  };

  let {
    currentRevision,
    initialPage,
    canRestore,
    hasUnsavedChanges,
    onLoadMore,
    onView,
    onRestore,
    onAnnounce,
    onRestored
  }: Props = $props();

  let revisions = $state(untrack(() => [...initialPage.items]));
  let nextCursor = $state(untrack(() => initialPage.next_cursor ?? null));
  let loadingMore = $state(false);
  let loadError = $state<string | null>(null);
  let viewingRevisionId = $state<string | null>(null);
  let previewError = $state<string | null>(null);
  let viewedRevision = $state<SkillRevisionPublic | null>(null);
  let restoreTarget = $state<SkillRevisionPublic | null>(null);
  let restoring = $state(false);
  let restoreError = $state<string | null>(null);

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

  async function viewRevision(revision: SkillRevisionSummaryPublic) {
    if (viewingRevisionId !== null) return;
    previewError = null;
    if (revision.id === currentRevision.id) {
      viewedRevision = currentRevision;
      return;
    }
    viewingRevisionId = revision.id;
    try {
      viewedRevision = await onView(revision.id);
    } catch (error) {
      previewError = getErrorMessage(error) || m.skills_library_preview_error();
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
      loadError = getErrorMessage(error) || m.skills_library_load_older_error();
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
      outcome = await onRestore(source.id);
    } catch (error) {
      restoreError = getErrorMessage(error) || m.skills_library_restore_error();
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
    await tick();
    if (outcome.created || outcome.revision.id !== currentRevision.id) {
      try {
        await onRestored?.(outcome);
      } catch {
        loadError = m.skills_library_restore_refresh_error();
      }
    }
  }

  function revisionTitle(revision: SkillRevisionPublic | SkillRevisionSummaryPublic): string {
    return m.skills_revision_label({ revision: String(revision.revision_number) });
  }
</script>

{#snippet revisionPreview(revision: SkillRevisionPublic, isCurrent = false)}
  <Card.Root>
    <Card.Header class="gap-2">
      <div class="flex flex-wrap items-center gap-2">
        <Card.Title class="text-base">{revisionTitle(revision)}</Card.Title>
        {#if isCurrent}
          <Badge variant="secondary">{m.skills_library_current_revision()}</Badge>
        {/if}
      </div>
      <Card.Description>{formatCreatedAt(revision.created_at)}</Card.Description>
    </Card.Header>
    <Card.Content>
      <dl class="flex flex-col gap-4">
        <div class="flex flex-col gap-1">
          <dt class="text-muted-foreground text-xs font-medium">{m.name()}</dt>
          <dd class="text-sm">{revision.display_name}</dd>
        </div>
        <div class="flex flex-col gap-1">
          <dt class="text-muted-foreground text-xs font-medium">{m.description()}</dt>
          <dd class="text-sm">{revision.description}</dd>
        </div>
        <div class="flex flex-col gap-1">
          <dt class="text-muted-foreground text-xs font-medium">
            {m.skills_instructions_label()}
          </dt>
          <dd
            class="border-border bg-muted/25 max-h-72 overflow-y-auto rounded-md border p-3 text-sm break-words whitespace-pre-wrap"
          >
            {revision.instructions}
          </dd>
        </div>
      </dl>
    </Card.Content>
  </Card.Root>
{/snippet}

<Card.Root>
  <Table.Root>
    <Table.Header>
      <Table.Row>
        <Table.Head>{m.skills_library_revision_column()}</Table.Head>
        <Table.Head>{m.name()}</Table.Head>
        <Table.Head>{m.skills_library_created_column()}</Table.Head>
        <Table.Head class="w-16 text-right">{m.actions()}</Table.Head>
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each revisions as revision (revision.id)}
        {@const isCurrent = revision.id === currentRevision.id}
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
          </Table.Cell>
          <Table.Cell>{revision.display_name}</Table.Cell>
          <Table.Cell class="text-muted-foreground text-sm">
            {formatCreatedAt(revision.created_at)}
          </Table.Cell>
          <Table.Cell class="text-right">
            <div class="flex items-center justify-end gap-1">
              <Button
                variant="ghost"
                size="icon-sm"
                disabled={viewingRevisionId !== null}
                title={m.view()}
                aria-label={m.skills_library_view_revision_aria({
                  revision: String(revision.revision_number)
                })}
                onclick={() => void viewRevision(revision)}
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
    <Card.Footer class="flex-col items-center gap-3 border-t">
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
    </Card.Footer>
  {/if}
</Card.Root>

<Dialog.Root
  open={viewedRevision !== null}
  onOpenChange={(open) => !open && (viewedRevision = null)}
>
  <Dialog.Content
    class="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl"
    closeLabel={m.close()}
  >
    <Dialog.Header>
      <Dialog.Title>
        {viewedRevision?.id === currentRevision.id
          ? m.skills_library_view_revision_title({
              revision: String(viewedRevision.revision_number)
            })
          : m.skills_library_compare_revision_title({
              revision: String(viewedRevision?.revision_number ?? "")
            })}
      </Dialog.Title>
      {#if viewedRevision?.id !== currentRevision.id}
        <Dialog.Description>{m.skills_library_compare_revision_description()}</Dialog.Description>
      {/if}
    </Dialog.Header>
    {#if viewedRevision}
      {#if viewedRevision.id === currentRevision.id}
        {@render revisionPreview(viewedRevision, true)}
      {:else}
        <div class="grid gap-4 md:grid-cols-2">
          {@render revisionPreview(viewedRevision)}
          {@render revisionPreview(currentRevision, true)}
        </div>
      {/if}
    {/if}
    <Dialog.Footer>
      {#if canRestore && viewedRevision && viewedRevision.id !== currentRevision.id}
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
  <AlertDialog.Content>
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
