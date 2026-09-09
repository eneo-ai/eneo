<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { LoaderCircle, SendHorizontal } from "lucide-svelte";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    /** Two-way bound textarea content. */
    value: string;
    /** True while a turn streams; disables the textarea and the send button. */
    disabled?: boolean;
    placeholder?: string;
    /** Bindable ref so the parent can refocus the input after each turn. */
    ref?: HTMLTextAreaElement | null;
    /** Called with the trimmed value when the user presses Enter or clicks Send. */
    onSubmit: (text: string) => void;
  };

  let {
    value = $bindable(""),
    disabled = false,
    placeholder = m.insights_chat_placeholder(),
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
    // Enter sends, Shift+Enter inserts a newline, as in the other chat surfaces.
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
      <!-- Not `disabled` while empty: InputGroup dims the whole box when any
           control inside is disabled, which reads as a disabled input. -->
      <InputGroup.Button
        type="submit"
        size="icon-sm"
        variant="default"
        class="ml-auto transition-opacity {canSend ? '' : 'opacity-40'}"
        aria-disabled={!canSend}
        aria-label={m.send_the_question()}
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
