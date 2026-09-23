<script lang="ts">
  import { tick } from "svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { LiveTranscriptPiece, LiveTranscriptStatus } from "./LiveTranscriptPreview.svelte";

  let {
    status,
    pieces
  }: {
    status: LiveTranscriptStatus;
    pieces: readonly LiveTranscriptPiece[];
  } = $props();

  const headingId = $props.id();
  const active = $derived(status === "connecting" || status === "listening");
  const hasText = $derived(pieces.length > 0);
  // After the recording, an empty panel would only say that nobody spoke.
  const ended = $derived(status === "interrupted" || status === "unavailable");
  const visible = $derived(active || ended || (status === "finished" && hasText));

  let log = $state<HTMLElement | null>(null);

  // Follow new text while the reader is at the end; someone who scrolled up to
  // reread keeps their place.
  $effect.pre(() => {
    void pieces.length;
    const element = log;
    if (!element) return;
    if (element.scrollHeight - element.scrollTop - element.clientHeight > 8) return;
    void tick().then(() => {
      element.scrollTop = element.scrollHeight;
    });
  });
</script>

{#if visible}
  <div class="mx-auto mt-4 w-full max-w-[36rem]">
    <div class="flex items-center justify-between gap-3">
      <h4 id={headingId} class="text-primary text-[0.8125rem] leading-snug font-bold">
        {m.live_transcription_heading()}
      </h4>
      <span
        role="status"
        class={[
          "inline-flex items-center gap-1.5 text-xs font-medium",
          status === "listening" ? "text-positive-stronger" : "text-secondary"
        ]}
      >
        {#if active}
          <span
            class={[
              "size-1.5 shrink-0 rounded-full",
              status === "listening" ? "bg-positive-default" : "bg-current"
            ]}
            aria-hidden="true"
          ></span>
          {status === "listening"
            ? m.live_transcription_listening()
            : m.live_transcription_connecting()}
        {/if}
      </span>
    </div>

    {#if ended}
      <!-- A preview that never got going is not an interruption. -->
      <Alert.Root
        class="border-warning-default/30 bg-warning-dimmer/70 text-warning-stronger mt-2 rounded-[9px] px-3.5 py-2.5 text-[0.8125rem]"
      >
        <Alert.Title>
          {status === "interrupted"
            ? m.live_transcription_interrupted()
            : m.live_transcription_unavailable()}
        </Alert.Title>
        <Alert.Description class="text-warning-stronger text-[0.8125rem]">
          {status === "interrupted"
            ? m.live_transcription_interrupted_detail()
            : m.live_transcription_unavailable_detail()}
        </Alert.Description>
      </Alert.Root>
    {/if}

    {#if active || hasText}
      <!-- Pieces are committed text and only ever appended, so a screen reader
           hears each new piece once and nothing on screen is rewritten. -->
      <!-- svelte-ignore a11y_no_noninteractive_tabindex (overflow region must be keyboard-scrollable) -->
      <div
        bind:this={log}
        role="log"
        aria-labelledby={headingId}
        tabindex="0"
        class="border-default bg-primary text-primary focus-visible:ring-ring mt-2 max-h-56 overflow-y-auto rounded-[9px] border px-3.5 py-2.5 text-[0.9375rem] leading-[1.6] outline-none focus-visible:ring-2"
      >
        {#if hasText}
          {#each pieces as piece (piece.id)}
            <span>{piece.text}</span>
          {/each}
        {:else}
          <span class="text-secondary">{m.live_transcription_empty()}</span>
        {/if}
      </div>
    {/if}

    {#if status === "finished"}
      <p class="text-secondary mt-2 text-[0.8125rem] leading-[1.6]">
        {m.live_transcription_draft_note()}
      </p>
    {/if}
  </div>
{/if}
