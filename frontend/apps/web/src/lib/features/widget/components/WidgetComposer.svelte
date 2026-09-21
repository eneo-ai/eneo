<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { IconSendArrow } from "@eneo/icons/send-arrow";

  type Props = {
    placeholder: string;
    maxLength: number;
    disabled: boolean;
    busy: boolean;
    suggestions: string[];
    showSuggestions: boolean;
    onSend: (question: string) => void;
    onEscape?: () => void;
  };

  let {
    placeholder,
    maxLength,
    disabled,
    busy,
    suggestions,
    showSuggestions,
    onSend,
    onEscape
  }: Props = $props();

  let value = $state("");
  let textarea = $state<HTMLTextAreaElement | null>(null);

  export function focus() {
    textarea?.focus();
  }

  const canSend = $derived(!disabled && !busy && value.trim().length > 0);

  function submit() {
    const question = value.trim();
    if (!question || disabled || busy) return;
    value = "";
    resize();
    onSend(question);
  }

  function resize() {
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape" && onEscape) {
      onEscape();
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submit();
    }
  }
</script>

<div class="flex flex-col gap-2">
  {#if showSuggestions && suggestions.length > 0}
    <ul class="flex flex-wrap gap-2" aria-label={m.widget_suggested_questions()}>
      <!-- Keyed by position: a repeated question must never take the panel down. -->
      {#each suggestions as suggestion, index (index)}
        <li>
          <button
            type="button"
            class="widget-chip bg-primary text-primary hover:bg-secondary focus-visible:ring-default border px-3 py-1.5 text-sm focus-visible:ring-2 focus-visible:outline-none"
            disabled={disabled || busy}
            onclick={() => onSend(suggestion)}
          >
            {suggestion}
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  <form
    class="widget-composer border-default bg-primary focus-within:border-stronger flex items-end gap-2 border px-3 py-2"
    onsubmit={(event) => {
      event.preventDefault();
      submit();
    }}
  >
    <label class="sr-only" for="widget-question">{m.widget_input_label()}</label>
    <textarea
      id="widget-question"
      bind:this={textarea}
      bind:value
      rows="1"
      maxlength={maxLength}
      {placeholder}
      {disabled}
      class="text-primary placeholder:text-secondary max-h-40 min-h-[2.25rem] flex-1 resize-none bg-transparent py-1 text-base leading-6 focus:outline-none disabled:opacity-60"
      oninput={resize}
      onkeydown={onKeydown}></textarea>
    <button
      type="submit"
      class="widget-send focus-visible:ring-default flex h-9 w-9 shrink-0 items-center justify-center rounded-full focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50"
      aria-label={m.widget_send()}
      disabled={!canSend}
    >
      <IconSendArrow size="sm" />
    </button>
  </form>
</div>

<style>
  .widget-chip {
    border-color: var(--widget-accent);
    border-radius: var(--widget-radius);
  }
  .widget-composer {
    border-radius: calc(var(--widget-radius) + 4px);
  }
  .widget-send {
    background: var(--widget-accent);
    color: var(--widget-on-accent);
  }
  .widget-send:not(:disabled):hover {
    filter: brightness(0.92);
  }
</style>
