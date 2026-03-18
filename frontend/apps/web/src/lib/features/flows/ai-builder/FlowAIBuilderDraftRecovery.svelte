<script lang="ts">
  import { Button, Dialog } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import type { AIBuilderDraftSession } from "./protocol";
  import { writable } from "svelte/store";

  interface Props {
    drafts: AIBuilderDraftSession[];
    onresume: (sessionId: string) => Promise<void> | void;
    onstartfresh: () => Promise<void> | void;
    ondiscard: (sessionId: string) => Promise<void> | void;
  }

  let { drafts, onresume, onstartfresh, ondiscard }: Props = $props();

  let confirmDeleteId = $state<string | null>(null);
  const showDeleteDialog = writable(false);

  function requestDiscard(sessionId: string) {
    confirmDeleteId = sessionId;
    showDeleteDialog.set(true);
  }

  function confirmDiscard() {
    if (confirmDeleteId) {
      ondiscard(confirmDeleteId);
      confirmDeleteId = null;
      showDeleteDialog.set(false);
    }
  }

  function cancelDiscard() {
    confirmDeleteId = null;
    showDeleteDialog.set(false);
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
    return date.toLocaleDateString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }

  function stepBadge(status: AIBuilderDraftSession["status"]): {
    label: string;
    variant: "discovering" | "confirming" | "building" | "reviewing";
  } {
    switch (status) {
      case "awaiting_approval":
        return { label: m.ai_builder_draft_step_reviewing(), variant: "reviewing" };
      case "applying":
        return { label: m.ai_builder_draft_step_building(), variant: "building" };
      default:
        return { label: m.ai_builder_draft_step_discovering(), variant: "discovering" };
    }
  }
</script>

<section class="draft-shell">
  <div class="draft-content">
    <div class="draft-header">
      <h2 class="draft-title">{m.ai_builder_drafts_title()}</h2>
      <p class="draft-subtitle">{m.ai_builder_drafts_subtitle()}</p>
    </div>

    <div class="draft-list">
      {#each drafts as draft, i (draft.session_id)}
        {@const badge = stepBadge(draft.status)}
        {@const isFirst = i === 0}
        <article class="draft-card" class:draft-card-highlighted={isFirst}>
          <div class="draft-card-main">
            <div class="draft-card-icon">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
                <path fill-rule="evenodd" d="M4.5 2A1.5 1.5 0 0 0 3 3.5v13A1.5 1.5 0 0 0 4.5 18h11a1.5 1.5 0 0 0 1.5-1.5V7.621a1.5 1.5 0 0 0-.44-1.06l-4.12-4.122A1.5 1.5 0 0 0 11.378 2H4.5Z" clip-rule="evenodd" />
              </svg>
            </div>
            <div class="draft-card-body">
              <h3 class="draft-card-title">{draft.draft_title ?? m.ai_builder_draft_untitled()}</h3>
              <div class="draft-card-meta">
                <span class="draft-timestamp">{formatRelativeTime(draft.updated_at)}</span>
                <span class="meta-dot">·</span>
                <span class="step-badge" class:badge-discovering={badge.variant === "discovering"} class:badge-confirming={badge.variant === "confirming"} class:badge-building={badge.variant === "building"} class:badge-reviewing={badge.variant === "reviewing"}>
                  {badge.label}
                </span>
              </div>
            </div>

            <div class="draft-card-actions">
              <button
                class="action-discard"
                onclick={() => requestDiscard(draft.session_id)}
                aria-label={m.ai_builder_discard_draft()}
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5">
                  <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
                </svg>
              </button>
              {#if isFirst}
                <Button variant="primary" size="small" onclick={() => onresume(draft.session_id)}>
                  {m.ai_builder_resume_draft()}
                </Button>
              {:else}
                <Button variant="outlined" size="small" onclick={() => onresume(draft.session_id)}>
                  {m.ai_builder_resume_draft()}
                </Button>
              {/if}
            </div>
          </div>
        </article>
      {/each}
    </div>

    <div class="new-flow-action">
      <Button variant="outlined" onclick={onstartfresh}>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
          <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
        </svg>
        {m.ai_builder_drafts_new()}
      </Button>
    </div>
  </div>
</section>

<!-- Delete confirmation dialog -->
<Dialog.Root openController={showDeleteDialog}>
  <Dialog.Content>
    <Dialog.Title>{m.ai_builder_draft_discard_title()}</Dialog.Title>
    <Dialog.Description>{m.ai_builder_draft_discard_body()}</Dialog.Description>
    <Dialog.Controls let:close>
      <Button variant="outlined" onclick={() => { cancelDiscard(); close(); }}>
        {m.cancel()}
      </Button>
      <Button variant="negative" onclick={() => { confirmDiscard(); close(); }}>
        {m.ai_builder_draft_discard_action()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<style lang="postcss">
  @reference "@intric/ui/styles";

  .draft-shell {
    display: flex;
    flex: 1;
    min-height: 0;
    align-items: flex-start;
    justify-content: center;
    padding: 3rem 1.5rem;
    overflow-y: auto;
  }

  .draft-content {
    display: flex;
    width: min(40rem, 100%);
    flex-direction: column;
    gap: 1.5rem;
  }

  /* --- Header --- */

  .draft-header {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .draft-title {
    font-size: 1.25rem;
    line-height: 1.2;
    font-weight: 650;
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }

  .draft-subtitle {
    color: var(--text-secondary);
    font-size: 0.875rem;
    line-height: 1.5;
  }

  /* --- Draft list --- */

  .draft-list {
    display: flex;
    flex-direction: column;
    gap: 0.625rem;
  }

  /* --- Draft card --- */

  .draft-card {
    border-radius: 0.75rem;
    border: 1px solid var(--border-default);
    background: var(--bg-primary);
    padding: 1rem 1.25rem;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }

  .draft-card:hover {
    border-color: var(--border-stronger);
    box-shadow: 0 1px 6px oklch(0 0 0 / 0.04);
  }

  .draft-card-highlighted {
    border-color: oklch(from var(--accent-default) l c h / 0.4);
    background: oklch(from var(--accent-default) l c h / 0.03);
  }

  .draft-card-highlighted:hover {
    border-color: oklch(from var(--accent-default) l c h / 0.6);
    box-shadow: 0 2px 8px oklch(from var(--accent-default) l c h / 0.08);
  }

  .draft-card-main {
    display: flex;
    align-items: flex-start;
    gap: 0.875rem;
  }

  .draft-card-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    flex-shrink: 0;
    border-radius: 0.5rem;
    background: var(--bg-secondary);
    color: var(--text-muted);
    margin-top: 0.125rem;
  }

  .draft-card-highlighted .draft-card-icon {
    background: oklch(from var(--accent-default) l c h / 0.1);
    color: var(--accent-default);
  }

  .draft-card-body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .draft-card-title {
    font-size: 0.9375rem;
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 1;
    -webkit-box-orient: vertical;
  }

  .draft-card-meta {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    font-size: 0.75rem;
  }

  .draft-timestamp {
    color: var(--text-muted);
  }

  .meta-dot {
    color: var(--text-muted);
  }

  /* --- Step badge --- */

  .step-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    border-radius: 999px;
    padding: 0.125rem 0.5rem;
    font-weight: 500;
    font-size: 0.6875rem;
    letter-spacing: 0.01em;
  }

  .badge-discovering {
    background: oklch(from var(--accent-default) l c h / 0.1);
    color: var(--accent-stronger);
  }

  .badge-confirming {
    background: oklch(from var(--accent-default) l c h / 0.1);
    color: var(--accent-stronger);
  }

  .badge-building {
    background: var(--bg-warning-dimmer);
    color: var(--text-warning-stronger);
  }

  .badge-reviewing {
    background: var(--bg-positive-dimmer);
    color: var(--text-positive-stronger);
  }

  /* --- Actions --- */

  .draft-card-actions {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    flex-shrink: 0;
    align-self: center;
  }

  .action-discard {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 0.375rem;
    border: none;
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    transition: color 0.15s ease, background 0.15s ease;
    flex-shrink: 0;
    opacity: 0;
  }

  .draft-card:hover .action-discard,
  .action-discard:focus-visible {
    opacity: 1;
  }

  .action-discard:hover {
    color: var(--text-negative-stronger);
    background: var(--bg-negative-dimmer);
  }

  .new-flow-action {
    display: flex;
    padding-top: 0.25rem;
  }

  /* --- Responsive --- */

  @media (max-width: 480px) {
    .draft-shell {
      padding: 1.5rem 1rem;
    }

    .draft-card-main {
      flex-wrap: wrap;
    }

    .draft-card-actions {
      width: 100%;
      justify-content: flex-end;
    }

    .action-discard {
      opacity: 1;
    }
  }
</style>
