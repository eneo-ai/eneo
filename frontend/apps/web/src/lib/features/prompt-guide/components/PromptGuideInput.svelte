<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { LoaderCircle, SendHorizontal } from "lucide-svelte";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    /** Two-way bound textarea content. */
    value: string;
    /**
     * True while a stream is in flight or no run is available. Disables both
     * the textarea and the send button so the user can't queue a second turn
     * on top of an active one (the run lifecycle isn't designed for it).
     */
    disabled?: boolean;
    /** Defaults to the standard "Reply to Prompt Guide…" string. */
    placeholder?: string;
    /** Bindable ref so the modal can refocus the input after each turn. */
    ref?: HTMLTextAreaElement | null;
    /** Called with the trimmed value when the user presses Enter or clicks Send. */
    onSubmit: (text: string) => void;
  };

  let {
    value = $bindable(""),
    disabled = false,
    placeholder = m.prompt_guide_input_placeholder(),
    ref = $bindable<HTMLTextAreaElement | null>(null),
    onSubmit
  }: Props = $props();

  const trimmed = $derived(value.trim());
  const canSend = $derived(!disabled && trimmed.length > 0);

  function submit() {
    if (!canSend) return;
    const text = trimmed;
    value = "";
    onSubmit(text);
  }

  function handleKeydown(event: KeyboardEvent) {
    // Enter sends, Shift+Enter inserts a newline — same convention as the
    // chat surfaces elsewhere in the app.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }
</script>

<form
  class="contents"
  onsubmit={(event) => {
    event.preventDefault();
    submit();
  }}
>
  <InputGroup.Root>
    <InputGroup.Textarea
      bind:ref
      bind:value
      onkeydown={handleKeydown}
      rows={2}
      {disabled}
      {placeholder}
      aria-label={placeholder}
      class="max-h-40 min-h-12"
    />
    <InputGroup.Addon align="block-end">
      <InputGroup.Button
        type="submit"
        size="icon-sm"
        variant="default"
        class="ml-auto"
        disabled={!canSend}
        aria-label={m.prompt_guide_question_send()}
      >
        {#if disabled}
          <LoaderCircle class="animate-spin" />
        {:else}
          <SendHorizontal />
        {/if}
      </InputGroup.Button>
    </InputGroup.Addon>
  </InputGroup.Root>
</form>
