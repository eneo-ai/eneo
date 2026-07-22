<script lang="ts">
  import type {
    SkillRevisionPublic,
    SkillRevisionSummaryPage,
    SkillRevisionSummaryPublic
  } from "@eneo/eneo-js";
  import { Eye, LoaderCircle } from "lucide-svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { untrack } from "svelte";

  type Props = {
    currentRevision: SkillRevisionPublic;
    initialPage: SkillRevisionSummaryPage;
    onLoadMore: (cursor: string) => Promise<SkillRevisionSummaryPage>;
    onView: (revisionId: string) => Promise<SkillRevisionPublic>;
  };

  let { currentRevision, initialPage, onLoadMore, onView }: Props = $props();

  let revisions = $state(untrack(() => [...initialPage.items]));
  let nextCursor = $state(untrack(() => initialPage.next_cursor ?? null));
  let loadingMore = $state(false);
  let loadError = $state<string | null>(null);
  let viewingRevisionId = $state<string | null>(null);
  let previewError = $state<string | null>(null);
  let viewedRevision = $state<SkillRevisionPublic | null>(null);

  function formatCreatedAt(value: string): string {
    return new Date(value).toLocaleString(getLocale() === "sv" ? "sv-SE" : "en-US", {
      dateStyle: "short",
      timeStyle: "short"
    });
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
      previewError = getErrorMessage(error);
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
      loadError = getErrorMessage(error);
    } finally {
      loadingMore = false;
    }
  }
</script>

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
        {m.skills_library_view_revision_title({
          revision: String(viewedRevision?.revision_number ?? "")
        })}
      </Dialog.Title>
      <Dialog.Description>{viewedRevision?.description}</Dialog.Description>
    </Dialog.Header>
    <div class="flex flex-col gap-1">
      <p class="text-muted-foreground text-xs font-medium">{m.name()}</p>
      <p class="text-foreground text-sm">{viewedRevision?.display_name}</p>
    </div>
    <div class="flex flex-col gap-1">
      <p class="text-muted-foreground text-xs font-medium">{m.skills_instructions_label()}</p>
      <div
        class="border-border bg-muted/25 max-h-[45vh] overflow-y-auto rounded-md border p-3 text-sm break-words whitespace-pre-wrap"
      >
        {viewedRevision?.instructions}
      </div>
    </div>
    <Dialog.Footer>
      <Button onclick={() => (viewedRevision = null)}>{m.close()}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
