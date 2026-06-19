<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<!--
  Transcript-style conversation region.

  Renders the Prompt Guide turn list as alternating question / answer lines —
  no chat-bubble framing, no avatars, no "Prompt Guide:" / "You:" labels.
  The LLM is instructed to be terse (see `defaults.py`) so the rendered
  output naturally reads as Q → A → Q; this component's job is to get out of
  the way.

  Each assistant turn is segmented via `extractStructuredQuestion`: prose
  before the structured block renders as markdown, the block itself renders
  as an interactive `PromptGuideQuestionCard`, prose after renders as
  markdown. Streaming-incomplete blocks are hidden behind a "Preparing a
  question…" placeholder so partial JSON never leaks to the user.
-->

<script lang="ts">
  import { LoaderCircle } from "lucide-svelte";
  import { tick } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { extractStructuredQuestion } from "../extractStructuredQuestion";
  import PromptGuideMarkdown from "./PromptGuideMarkdown.svelte";
  import PromptGuideQuestionCard from "./PromptGuideQuestionCard.svelte";

  export type Turn = {
    role: "user" | "assistant";
    text: string;
    isStreaming: boolean;
  };

  type Props = {
    turns: Turn[];
    /** True while a turn is streaming — disables interactive card submission. */
    isStreaming: boolean;
    /**
     * Whether the modal opened with a non-empty captured prompt. Used for the
     * "Reviewing your instructions…" status on the very first turn, which is
     * the only place we keep long status text (per "transcript, not chat" —
     * everything else is a small spinner).
     */
    hasCapturedPrompt: boolean;
    /** Called when the user submits a structured question card. */
    onQuestionAnswer: (text: string) => void;
  };

  let { turns, isStreaming, hasCapturedPrompt, onQuestionAnswer }: Props = $props();

  let scrollEl = $state<HTMLDivElement>();

  // Auto-scroll to bottom whenever turns grow or the streaming turn extends.
  // Triggered by accumulating turns.length + the streaming turn's text length
  // so it tracks chunk-by-chunk during a stream.
  const lastTurnLength = $derived(turns.at(-1)?.text.length ?? 0);
  $effect(() => {
    // Read the deps so the effect re-runs.
    void turns.length;
    void lastTurnLength;
    void tick().then(() => {
      if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
    });
  });
</script>

<div
  bind:this={scrollEl}
  class="border-default bg-subtle min-h-72 flex-1 overflow-y-auto rounded-lg border p-4"
  aria-live="polite"
  aria-busy={isStreaming}
  aria-label={m.prompt_guide_streaming_announcement()}
>
  {#if turns.length === 0}
    <div
      class="text-muted flex h-full flex-col items-center justify-center gap-2 text-center text-sm"
      role="status"
    >
      <LoaderCircle class="size-5 animate-spin" aria-hidden="true" />
      <p>{m.prompt_guide_analyzing()}</p>
    </div>
  {:else}
    <ul class="flex flex-col gap-4">
      {#each turns as turn, index (index)}
        <li class="text-sm">
          {#if turn.role === "user"}
            <!-- User turn: subtle right-aligned line, no avatar, no "You:" label. -->
            <div class="text-secondary flex justify-end">
              <div class="break-words whitespace-pre-wrap">{turn.text}</div>
            </div>
          {:else if turn.isStreaming && turn.text.length === 0}
            <!-- Streaming placeholder: small spinner-only row. The longer
                 "Reviewing your instructions…" status is reserved for the
                 very first turn when there was an existing prompt to
                 analyse — everywhere else, the model has been told to be
                 terse, so a single quiet spinner matches that cadence. -->
            <div class="text-muted flex items-center gap-2" role="status">
              <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
              {#if index === 0 && hasCapturedPrompt}
                <span>{m.prompt_guide_analyzing()}</span>
              {/if}
            </div>
          {:else}
            {@const segment = extractStructuredQuestion(turn.text)}
            <div class="flex flex-col gap-2">
              {#if segment.kind === "parsed"}
                {#if segment.proseBefore.trim()}
                  <PromptGuideMarkdown source={segment.proseBefore} class="text-default" />
                {/if}
                <PromptGuideQuestionCard
                  question={segment.question}
                  disabled={isStreaming}
                  onAnswer={onQuestionAnswer}
                />
                {#if segment.proseAfter.trim()}
                  <PromptGuideMarkdown source={segment.proseAfter} class="text-default" />
                {/if}
              {:else if segment.kind === "pending"}
                {#if segment.proseBefore.trim()}
                  <PromptGuideMarkdown source={segment.proseBefore} class="text-default" />
                {/if}
                <div class="text-muted flex items-center gap-2 text-xs italic" role="status">
                  <LoaderCircle class="size-3.5 animate-spin" aria-hidden="true" />
                  <span>{m.prompt_guide_question_thinking()}</span>
                </div>
              {:else}
                <!-- 'invalid' and 'none' both render the raw turn text. For
                     'invalid' the malformed `eneo-question` block surfaces as
                     a normal code block via PromptGuideMarkdown; the user can
                     still type a free-text reply through the bottom input. -->
                <PromptGuideMarkdown source={turn.text} class="text-default" />
              {/if}
              {#if turn.isStreaming}
                <span class="sr-only">{m.prompt_guide_streaming_announcement()}</span>
                <span
                  class="bg-primary ml-0.5 inline-block h-4 w-0.5 animate-pulse align-middle"
                  aria-hidden="true"
                ></span>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>
