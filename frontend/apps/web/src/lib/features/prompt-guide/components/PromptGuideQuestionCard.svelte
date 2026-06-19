<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<!--
  Claude-Code-style multi-choice question card.

  Rendered in place of the raw ` ```eneo-question ` fenced block once
  `extractStructuredQuestion` confirms a complete envelope. Always offers a
  sibling "Other (write your own)" free-text field — placed as a SIBLING of
  the radiogroup (not inside it) so the radiogroup's ARIA semantics stay
  clean and keyboard navigation matches user expectation.

  For single-select questions the radio and the "Other" field are mutually
  exclusive (typing in Other deselects the radio, picking a radio clears
  Other) — that matches Claude Code's `AskUserQuestion`. For multi-select
  they coexist and the submitted answer concatenates picked labels with the
  "Other" text.
-->

<script lang="ts">
  import { fade } from "svelte/transition";
  import { tick, untrack } from "svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { PromptGuideQuestion } from "../extractStructuredQuestion";

  type Props = {
    question: PromptGuideQuestion;
    /** True while the modal is streaming — disables submission until the stream ends. */
    disabled?: boolean;
    /** Called with the user's combined answer text (label + Other). */
    onAnswer: (text: string) => void;
  };

  let { question, disabled = false, onAnswer }: Props = $props();

  // Latch onto the first valid `question` prop we receive. Weak / over-
  // chatty models sometimes keep streaming additional `eneo-question`
  // blocks after the closing fence (against the system prompt's rules) —
  // the parser then "follows" the LATEST block, swapping the prop under
  // the card while the user is in the middle of answering. Latching pins
  // the visible question to the first one so the user's in-progress
  // selections and typing are never reset by an LLM that won't stop.
  let latchedQuestion = $state<PromptGuideQuestion | null>(null);
  $effect(() => {
    if (latchedQuestion === null) {
      const incoming = question;
      untrack(() => {
        latchedQuestion = incoming;
      });
    }
  });
  const q = $derived(latchedQuestion ?? question);

  let radioValue = $state<string>("");
  // The card is mounted once per turn; options length is fixed for that
  // mount even if the parser re-runs as the stream tails on. `untrack` makes
  // that contract explicit and silences Svelte's "reference captures initial
  // value" warning.
  let checkedFlags = $state<boolean[]>(untrack(() => q.options.map(() => false)));
  let otherText = $state<string>("");
  let submitted = $state(false);
  let cardElement = $state<HTMLDivElement>();

  // Auto-focus the first interactive control on mount so keyboard users land
  // inside the card. Scope to the card element so multiple cards on the page
  // don't fight each other for focus.
  $effect(() => {
    void tick().then(() =>
      untrack(() => {
        // Multi-choice cards focus the first radio / checkbox; free-text
        // intake cards focus the textarea. The `textarea` selector handles
        // the latter — for multi-choice cards a radio/checkbox always
        // appears in the DOM before the "Other" input, so the selector's
        // left-to-right order resolves correctly.
        cardElement
          ?.querySelector<HTMLElement>(
            "[data-slot=radio-group-item], [data-slot=checkbox], textarea"
          )
          ?.focus();
      })
    );
  });

  // Enter sends, Shift+Enter inserts a newline — same convention as the
  // rest of the app. Used by the free-text intake textarea.
  function handleTextareaKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  // Single-select: typing in Other clears the radio, picking a radio clears
  // Other. Multi-select keeps both visible so the user can layer an "Also: …"
  // note onto a multi-pick.
  $effect(() => {
    if (q.multiSelect) return;
    if (radioValue !== "" && otherText.length > 0) {
      untrack(() => {
        otherText = "";
      });
    }
  });

  $effect(() => {
    if (q.multiSelect) return;
    if (otherText.length > 0 && radioValue !== "") {
      untrack(() => {
        radioValue = "";
      });
    }
  });

  // Two-stage gating: the inputs themselves stay typeable / pickable as
  // long as the card hasn't been submitted (so the user can compose their
  // reply WHILE a chatty model keeps streaming — weak models that don't
  // stop after the closing fence used to make the textarea silently
  // unresponsive). Only the Send button is gated by `disabled` (the
  // streaming flag), via this `canSubmit` derived.
  const canSubmit = $derived.by(() => {
    if (submitted || disabled) return false;
    if (otherText.trim().length > 0) return true;
    if (q.multiSelect) return checkedFlags.some((c) => c);
    return radioValue !== "";
  });

  function answerText(): string {
    const picked: string[] = [];
    if (q.multiSelect) {
      for (let i = 0; i < q.options.length; i++) {
        if (checkedFlags[i]) picked.push(q.options[i].label);
      }
    } else if (radioValue !== "") {
      const idx = Number.parseInt(radioValue, 10);
      if (Number.isFinite(idx) && q.options[idx]) {
        picked.push(q.options[idx].label);
      }
    }
    const other = otherText.trim();
    if (other.length > 0) picked.push(other);
    return picked.join(", ");
  }

  function submit() {
    if (!canSubmit) return;
    const text = answerText();
    submitted = true;
    onAnswer(text);
  }

  // Stable id pair so `aria-labelledby` / `for` work across multiple cards on
  // the page. Built from `question` content so two different questions never
  // collide even within one assistant turn.
  const cardId = $derived(
    `pg-q-${q.header.replace(/\s+/g, "-").toLowerCase()}-${q.question.length}`
  );
  const titleId = $derived(`${cardId}-title`);
  const otherInputId = $derived(`${cardId}-other`);
</script>

<div
  bind:this={cardElement}
  class="border-default bg-primary rounded-lg border p-4 transition-opacity {submitted
    ? 'opacity-60'
    : ''}"
  transition:fade={{ duration: 150 }}
  aria-busy={submitted}
>
  <div class="text-muted mb-1 text-xs font-medium tracking-wide uppercase">
    {q.header}
  </div>
  <div id={titleId} class="text-default mb-3 text-sm font-medium">
    {q.question}
  </div>

  {#if q.options.length > 0}
    {#if q.multiSelect}
      <fieldset class="flex flex-col gap-2" disabled={submitted} aria-labelledby={titleId}>
        <legend class="sr-only">{q.question}</legend>
        {#each q.options as option, index (index)}
          {@const id = `${cardId}-opt-${index}`}
          <Label
            for={id}
            class="hover:bg-hover-dimmer flex cursor-pointer items-start gap-3 rounded-md p-2"
          >
            <Checkbox {id} bind:checked={checkedFlags[index]} disabled={submitted} class="mt-0.5" />
            <span class="flex-1 text-sm">
              <span class="text-default block font-medium">{option.label}</span>
              {#if option.description}
                <span class="text-muted block text-xs">{option.description}</span>
              {/if}
            </span>
          </Label>
        {/each}
      </fieldset>
    {:else}
      <RadioGroup.Root
        bind:value={radioValue}
        disabled={submitted}
        aria-labelledby={titleId}
        class="gap-2"
      >
        {#each q.options as option, index (index)}
          {@const id = `${cardId}-opt-${index}`}
          <Label
            for={id}
            class="hover:bg-hover-dimmer flex cursor-pointer items-start gap-3 rounded-md p-2"
          >
            <RadioGroup.Item value={String(index)} {id} disabled={submitted} class="mt-0.5" />
            <span class="flex-1 text-sm">
              <span class="text-default block font-medium">{option.label}</span>
              {#if option.description}
                <span class="text-muted block text-xs">{option.description}</span>
              {/if}
            </span>
          </Label>
        {/each}
      </RadioGroup.Root>
    {/if}
  {/if}

  {#if q.options.length === 0}
    <!-- Free-text intake mode: the input is the primary affordance, not an
         "Other" escape hatch — render a generous textarea, not an inline
         input. The system prompt requires the first interview question to
         take this shape. -->
    <Label for={otherInputId} class="text-default mb-2 block text-sm font-medium">
      {m.prompt_guide_question_free_answer_label()}
    </Label>
    <div class="flex flex-col gap-2">
      <Textarea
        id={otherInputId}
        bind:value={otherText}
        onkeydown={handleTextareaKeydown}
        placeholder={m.prompt_guide_question_free_answer_placeholder()}
        disabled={submitted}
        rows={3}
        class="resize-none"
      />
      <Button size="sm" disabled={!canSubmit} onclick={submit} class="self-end">
        {m.prompt_guide_question_send()}
      </Button>
    </div>
  {:else}
    <div class="mt-3">
      <Label for={otherInputId} class="text-muted mb-1 block text-xs">
        {m.prompt_guide_question_other_label()}
      </Label>
      <div class="flex items-stretch gap-2">
        <input
          id={otherInputId}
          type="text"
          bind:value={otherText}
          placeholder={m.prompt_guide_question_other_placeholder()}
          disabled={submitted}
          class="border-default bg-primary ring-default flex-1 rounded-md border px-3 py-1.5 text-sm shadow-sm focus-within:ring-2 hover:ring-2 focus-visible:ring-2 disabled:opacity-60"
        />
        <Button size="sm" disabled={!canSubmit} onclick={submit}>
          {m.prompt_guide_question_send()}
        </Button>
      </div>
    </div>
  {/if}
</div>
