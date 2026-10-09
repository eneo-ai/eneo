<!--
  Thumbs on the conversation, the acknowledgement, and the opt-in comment
  dialog. State is keyed by conversation id so a new conversation starts
  clean while an earlier one keeps what the visitor already did; a restored
  conversation shows the vote the server remembers. The chat keeps this
  mounted across follow-up questions, so the state lives as long as the
  conversation does.
-->
<script lang="ts">
  import { tick } from "svelte";
  import { Check, ThumbsDown, ThumbsUp } from "@lucide/svelte";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";

  type Vote = 1 | -1;

  let {
    sessionId,
    collectsText,
    restored = null,
    disabled = false,
    submit
  }: {
    sessionId: string;
    /** The widget stores comments; without it only the thumbs are offered. */
    collectsText: boolean;
    /** While the next answer is on its way. */
    disabled?: boolean;
    /** The vote the server already holds for a restored conversation. */
    restored?: { value: Vote; text?: string | null } | null;
    /** Sends a vote (with an optional comment); resolves to the visitor-facing error, or null. */
    submit: (feedback: { value: Vote; text?: string }) => Promise<string | null>;
  } = $props();

  let votes = $state<Record<string, Vote>>({});
  let comments = $state<Record<string, string>>({});
  let editing = $state(false);
  let changeButton = $state<HTMLButtonElement | null>(null);
  let voting = $state(false);
  let dialogOpen = $state(false);
  let text = $state("");
  let sending = $state(false);
  let helpfulButton = $state<HTMLButtonElement | null>(null);
  let unhelpfulButton = $state<HTMLButtonElement | null>(null);
  // A successful comment changes its opener label. Return to the stable
  // change-vote control when the dialog closes.
  let refocusChange = false;
  // Shown where the visitor is looking: inside the dialog while it is open,
  // otherwise under the thumbs. A footer alert would hide behind the overlay.
  let error = $state<string | null>(null);
  let questionGeneration = 0;

  const given = $derived<Vote | undefined>(votes[sessionId] ?? restored?.value ?? undefined);
  // A later vote keeps a stored comment (it is sent without text), so this
  // stays true across vote changes.
  const savedComment = $derived(comments[sessionId] ?? restored?.text ?? "");
  const sent = $derived(!!savedComment);

  // A failed feedback request belongs to that attempt. A new question owns
  // the next error location; do not leave the old alert beside it.
  $effect(() => {
    if (disabled) {
      questionGeneration += 1;
      error = null;
      editing = false;
    }
  });

  async function finishVoting() {
    editing = false;
    await tick();
    changeButton?.focus({ preventScroll: true });
  }

  async function changeVote() {
    editing = !editing;
    if (editing) {
      await tick();
      (given === -1 ? unhelpfulButton : helpfulButton)?.focus({ preventScroll: true });
    }
  }

  async function vote(value: Vote) {
    if (voting || disabled) return;
    if (given === value) return finishVoting();
    voting = true;
    error = null;
    const generation = questionGeneration;
    try {
      const failure = await submit({ value });
      if (generation === questionGeneration) error = failure;
      if (!failure) {
        votes = { ...votes, [sessionId]: value };
        if (generation === questionGeneration) await finishVoting();
      }
    } finally {
      voting = false;
    }
  }

  async function sendComment() {
    const value = given;
    const comment = text.trim();
    if (!value || !comment || sending) return;
    sending = true;
    error = null;
    try {
      error = await submit({ value, text: comment });
      if (!error) {
        comments = { ...comments, [sessionId]: comment };
        text = "";
        refocusChange = true;
        dialogOpen = false;
      }
    } finally {
      sending = false;
    }
  }

  function openDialog() {
    text = savedComment;
    error = null;
    dialogOpen = true;
  }

  function onCloseAutoFocus(event: Event) {
    if (!refocusChange) return;
    refocusChange = false;
    event.preventDefault();
    changeButton?.focus({ preventScroll: true });
  }
</script>

{#if !given || editing}
  <div class="mt-3 flex items-center gap-2" role="group" aria-labelledby="widget-feedback-prompt">
    <span id="widget-feedback-prompt" class="text-secondary text-xs">
      {m.widget_feedback_prompt()}
    </span>
    <button
      type="button"
      bind:this={helpfulButton}
      class={[
        "flex min-h-11 min-w-11 items-center justify-center rounded-full disabled:opacity-50",
        given === 1 ? "bg-accent-dimmer text-accent-default" : "text-secondary hover:bg-secondary"
      ]}
      aria-label={m.widget_feedback_helpful()}
      aria-pressed={given === 1}
      {disabled}
      onclick={() => vote(1)}
    >
      <ThumbsUp class="size-4" aria-hidden="true" />
    </button>
    <button
      type="button"
      bind:this={unhelpfulButton}
      class={[
        "flex min-h-11 min-w-11 items-center justify-center rounded-full disabled:opacity-50",
        given === -1 ? "bg-accent-dimmer text-accent-default" : "text-secondary hover:bg-secondary"
      ]}
      aria-label={m.widget_feedback_unhelpful()}
      aria-pressed={given === -1}
      {disabled}
      onclick={() => vote(-1)}
    >
      <ThumbsDown class="size-4" aria-hidden="true" />
    </button>
  </div>
{/if}
<!-- Always rendered: screen readers announce a change to a status region, not
     one that appears with its text already in it. A restored vote is shown
     without being announced. -->
<div role="status">
  {#if given}
    <p class="widget-enter text-secondary mt-2 flex items-center gap-1.5 text-xs">
      <Check class="text-positive-default size-3.5 shrink-0" aria-hidden="true" />
      {sent ? m.widget_feedback_received() : m.widget_feedback_thanks()}
    </p>
  {/if}
</div>
{#if given}
  <div class="widget-enter flex flex-wrap items-center gap-x-3">
    <button
      type="button"
      bind:this={changeButton}
      class="text-accent-default min-h-11 rounded-md text-xs underline-offset-2 hover:underline disabled:opacity-50"
      aria-expanded={editing}
      {disabled}
      onclick={changeVote}
    >
      {m.widget_feedback_change()}
    </button>
    {#if collectsText}
      <button
        type="button"
        class="text-accent-default min-h-11 w-fit rounded-md text-xs underline-offset-2 hover:underline disabled:opacity-50"
        {disabled}
        onclick={openDialog}
      >
        {sent
          ? m.widget_feedback_edit_comment()
          : given === -1
            ? m.widget_feedback_more_negative()
            : m.widget_feedback_more()}
      </button>
    {/if}
  </div>
{/if}
{#if error && !dialogOpen}
  <p
    role="alert"
    class="bg-negative-dimmer text-negative-default mt-2 rounded-lg px-3 py-2 text-xs"
  >
    {error}
  </p>
{/if}

<Dialog.Root bind:open={dialogOpen}>
  <Dialog.Content
    class="max-w-[calc(100%-2rem)] sm:max-w-md"
    closeLabel={m.close()}
    {onCloseAutoFocus}
  >
    <form
      class="flex flex-col gap-4"
      onsubmit={(event) => {
        event.preventDefault();
        void sendComment();
      }}
    >
      <Dialog.Header>
        <Dialog.Title>{m.widget_feedback_more_title()}</Dialog.Title>
        <Dialog.Description>{m.widget_feedback_more_body()}</Dialog.Description>
      </Dialog.Header>
      <textarea
        class="border-default bg-primary text-primary w-full resize-y rounded-lg border px-3 py-2 text-sm"
        rows="4"
        maxlength="2000"
        aria-label={m.widget_feedback_more_title()}
        placeholder={given === -1
          ? m.widget_feedback_more_placeholder_negative()
          : m.widget_feedback_more_placeholder()}
        bind:value={text}></textarea>
      {#if error && dialogOpen}
        <p
          role="alert"
          class="bg-negative-dimmer text-negative-default rounded-lg px-3 py-2 text-sm"
        >
          {error}
        </p>
      {/if}
      <Dialog.Footer>
        <Dialog.Close>
          {#snippet child({ props })}
            <Button variant="outline" {...props}>{m.cancel()}</Button>
          {/snippet}
        </Dialog.Close>
        <!-- Not disabled while sending: focus would fall off the button. -->
        <Button type="submit" disabled={!text.trim()}>
          {sending ? m.widget_feedback_sending() : m.widget_feedback_send()}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
