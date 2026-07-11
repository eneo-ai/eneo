<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { RecoverableAIBuilderDraftSession } from "./protocol";

  interface Props {
    drafts: RecoverableAIBuilderDraftSession[];
    onresume: (sessionId: string) => Promise<void> | void;
    onstartfresh: () => Promise<void> | void;
    ondiscard: (sessionId: string) => Promise<void> | void;
  }

  let { drafts, onresume, onstartfresh, ondiscard }: Props = $props();

  let confirmDeleteId = $state<string | null>(null);
  let showDeleteDialog = $state(false);

  function requestDiscard(sessionId: string) {
    confirmDeleteId = sessionId;
    showDeleteDialog = true;
  }

  function confirmDiscard() {
    if (confirmDeleteId) {
      ondiscard(confirmDeleteId);
      confirmDeleteId = null;
      showDeleteDialog = false;
    }
  }

  function cancelDiscard() {
    confirmDeleteId = null;
    showDeleteDialog = false;
  }

  function formatRelativeTime(value?: string | null): string {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";

    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60_000);
    const diffHours = Math.floor(diffMs / 3_600_000);
    const diffDays = Math.floor(diffMs / 86_400_000);

    if (diffMin < 1) return m.ai_builder_draft_just_now();
    if (diffMin < 60) return `${diffMin} min`;
    if (diffHours < 24 && now.getDate() === date.getDate()) {
      return `${m.ai_builder_draft_today()} ${date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
    }
    if (diffDays < 2) {
      return `${m.ai_builder_draft_yesterday()} ${date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
    }
    return date.toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function stepBadge(status: RecoverableAIBuilderDraftSession["status"]): {
    label: string;
    variant: "discovering" | "confirming" | "building" | "reviewing";
  } {
    switch (status) {
      case "awaiting_approval":
        return { label: m.ai_builder_draft_step_reviewing(), variant: "reviewing" };
      case "chatting":
        return { label: m.ai_builder_draft_step_discovering(), variant: "discovering" };
    }
  }
</script>

<section
  class="flex min-h-0 flex-1 items-start justify-center overflow-y-auto px-6 py-14 max-[480px]:px-4 max-[480px]:py-8"
>
  <div class="flex w-full max-w-[40rem] flex-col gap-7">
    <header class="flex flex-col gap-1.5">
      <h2 class="text-primary text-[1.375rem] leading-tight font-semibold tracking-[-0.01em]">
        {m.ai_builder_drafts_title()}
      </h2>
      <p class="text-secondary text-[0.9375rem] leading-relaxed">
        {m.ai_builder_drafts_subtitle()}
      </p>
    </header>

    <ol class="flex flex-col gap-2.5" role="list">
      {#each drafts as draft, i (draft.session_id)}
        {@const badge = stepBadge(draft.status)}
        {@const isFirst = i === 0}
        <li>
          <Card.Root
            class="group/draft-card !gap-0 !py-0 transition-[border-color,box-shadow] duration-150 {isFirst
              ? 'border-accent-default/40 bg-accent-default/[0.02] hover:border-accent-default/60'
              : 'hover:border-stronger hover:shadow-sm'}"
          >
            <div class="flex items-start gap-3.5 px-5 py-4 max-[480px]:flex-wrap">
              <div
                class="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg {isFirst
                  ? 'bg-accent-default/10 text-accent-default'
                  : 'bg-secondary text-muted'}"
                aria-hidden="true"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  class="size-4"
                >
                  <path
                    fill-rule="evenodd"
                    d="M4.5 2A1.5 1.5 0 0 0 3 3.5v13A1.5 1.5 0 0 0 4.5 18h11a1.5 1.5 0 0 0 1.5-1.5V7.621a1.5 1.5 0 0 0-.44-1.06l-4.12-4.122A1.5 1.5 0 0 0 11.378 2H4.5Z"
                    clip-rule="evenodd"
                  />
                </svg>
              </div>
              <div class="flex min-w-0 flex-1 flex-col gap-1.5">
                <h3 class="text-primary line-clamp-1 text-[0.9375rem] leading-snug font-semibold">
                  {draft.draft_title ?? m.ai_builder_draft_untitled()}
                </h3>
                <div class="flex items-center gap-1.5 text-xs">
                  <span class="text-muted">{formatRelativeTime(draft.updated_at)}</span>
                  <span class="text-muted" aria-hidden="true">&middot;</span>
                  <Badge
                    variant="outline"
                    class="h-auto rounded-full border-transparent px-2 py-0.5 text-xs font-medium tracking-[0.01em] {badge.variant ===
                    'building'
                      ? 'bg-warning-dimmer text-warning-stronger'
                      : badge.variant === 'reviewing'
                        ? 'bg-positive-dimmer text-positive-stronger'
                        : 'bg-accent-default/10 text-accent-stronger'}"
                  >
                    {badge.label}
                  </Badge>
                </div>
              </div>

              <div
                class="flex shrink-0 items-center gap-1.5 self-center max-[480px]:w-full max-[480px]:justify-end"
              >
                <button
                  type="button"
                  class="text-muted hover:bg-negative-dimmer hover:text-negative-stronger flex size-7 shrink-0 items-center justify-center rounded-md transition-colors duration-150"
                  onclick={() => requestDiscard(draft.session_id)}
                  aria-label={m.ai_builder_discard_draft()}
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                    class="size-3.5"
                    aria-hidden="true"
                  >
                    <path
                      fill-rule="evenodd"
                      d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z"
                      clip-rule="evenodd"
                    />
                  </svg>
                </button>
                {#if isFirst}
                  <Button variant="default" size="sm" onclick={() => onresume(draft.session_id)}>
                    {m.ai_builder_resume_draft()}
                  </Button>
                {:else}
                  <Button variant="outline" size="sm" onclick={() => onresume(draft.session_id)}>
                    {m.ai_builder_resume_draft()}
                  </Button>
                {/if}
              </div>
            </div>
          </Card.Root>
        </li>
      {/each}
    </ol>

    <Separator />

    <div class="flex pt-1">
      <Button variant="outline" onclick={onstartfresh}>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          class="size-4"
          aria-hidden="true"
        >
          <path
            d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z"
          />
        </svg>
        {m.ai_builder_drafts_new()}
      </Button>
    </div>
  </div>
</section>

<AlertDialog.Root bind:open={showDeleteDialog}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.ai_builder_draft_discard_title()}</AlertDialog.Title>
      <AlertDialog.Description>{m.ai_builder_draft_discard_body()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel onclick={cancelDiscard}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={confirmDiscard}>
        {m.ai_builder_draft_discard_action()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
