<!--
  Thumbs on the conversation, the acknowledgement, and the opt-in comment
  dialog. State is keyed by conversation id so a new conversation starts
  clean while an earlier one keeps what the visitor already did; a restored
  conversation shows the vote the server remembers.
-->
<script lang="ts">
  import { Check, ThumbsDown, ThumbsUp } from "lucide-svelte";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";

  type Vote = 1 | -1;

  let {
    sessionId,
    collectsText,
    restored = null,
    submit
  }: {
    sessionId: string;
    /** The widget stores comments; without it only the thumbs are offered. */
    collectsText: boolean;
    /** The vote the server already holds for a restored conversation. */
    restored?: { value: Vote; text?: string | null } | null;
    /** Sends a vote (with an optional comment); resolves to the visitor-facing error, or null. */
    submit: (feedback: { value: Vote; text?: string }) => Promise<string | null>;
  } = $props();

  let votes = $state<Record<string, Vote>>({});
  let commented = $state<Record<string, true>>({});
  let voting = $state(false);
  let dialogOpen = $state(false);
  let text = $state("");
  let sending = $state(false);
  // Shown where the visitor is looking: inside the dialog while it is open,
  // otherwise under the thumbs. A footer alert would hide behind the overlay.
  let error = $state<string | null>(null);

  const given = $derived<Vote | undefined>(votes[sessionId] ?? restored?.value ?? undefined);
  const sent = $derived(commented[sessionId] === true || !!restored?.text);

  async function vote(value: Vote) {
    if (given === value || voting) return;
    voting = true;
    error = null;
    try {
      error = await submit({ value });
      if (!error) votes = { ...votes, [sessionId]: value };
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
        commented = { ...commented, [sessionId]: true };
        text = "";
        dialogOpen = false;
      }
    } finally {
      sending = false;
    }
  }

  function openDialog() {
    error = null;
    dialogOpen = true;
  }
</script>

<div class="mt-3 flex items-center gap-2" role="group" aria-labelledby="widget-feedback-prompt">
  <span id="widget-feedback-prompt" class="text-secondary text-xs">
    {m.widget_feedback_prompt()}
  </span>
  <button
    type="button"
    class={[
      "focus-visible:ring-default flex h-8 w-8 items-center justify-center rounded-full focus-visible:ring-2 focus-visible:outline-none",
      given === 1 ? "bg-accent-dimmer text-accent-default" : "text-secondary hover:bg-secondary"
    ]}
    aria-label={m.widget_feedback_helpful()}
    aria-pressed={given === 1}
    onclick={() => vote(1)}
  >
    <ThumbsUp class="size-4" aria-hidden="true" />
  </button>
  <button
    type="button"
    class={[
      "focus-visible:ring-default flex h-8 w-8 items-center justify-center rounded-full focus-visible:ring-2 focus-visible:outline-none",
      given === -1 ? "bg-accent-dimmer text-accent-default" : "text-secondary hover:bg-secondary"
    ]}
    aria-label={m.widget_feedback_unhelpful()}
    aria-pressed={given === -1}
    onclick={() => vote(-1)}
  >
    <ThumbsDown class="size-4" aria-hidden="true" />
  </button>
</div>
<!-- Always rendered: screen readers announce a change to a status region, not
     one that appears with its text already in it. A restored vote is shown
     without being announced. -->
<div role="status">
  {#if given}
    <p class="text-secondary mt-2 flex items-center gap-1.5 text-xs">
      <Check class="text-positive-default size-3.5 shrink-0" aria-hidden="true" />
      {sent ? m.widget_feedback_received() : m.widget_feedback_thanks()}
    </p>
  {/if}
</div>
{#if given}
  {#if collectsText && !sent}
    <button
      type="button"
      class="text-accent-default focus-visible:ring-default mt-1 w-fit rounded-md text-xs underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
      onclick={openDialog}
    >
      {given === -1 ? m.widget_feedback_more_negative() : m.widget_feedback_more()}
    </button>
  {/if}
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
  <Dialog.Content class="max-w-[calc(100%-2rem)] sm:max-w-md">
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
        class="border-default bg-primary text-primary focus-visible:ring-default w-full resize-y rounded-lg border px-3 py-2 text-sm focus-visible:ring-2 focus-visible:outline-none"
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
        <Button type="submit" disabled={!text.trim() || sending}>
          {sending ? m.widget_feedback_sending() : m.widget_feedback_send()}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
