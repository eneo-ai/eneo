<script lang="ts">
  import { tick } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import IconX from "@lucide/svelte/icons/x";

  interface Props {
    open: boolean;
    text?: string;
    /** "Steg 3: Rendera PDF" when the request is scoped to one step. */
    scopeLabel?: string | null;
    disabled?: boolean;
    /** What this box rewrites. Defaults to the plan; the confirmation screen
     *  passes its own words because it rewrites the summary instead. */
    title?: string;
    example?: string;
    placeholder?: string;
    hint?: string;
    onclearscope?: () => void;
    /** The collapsed opener asks to be opened rather than opening itself: the
     *  owner decides what else has to close first. */
    onopen?: () => void;
    onsend: (text: string) => void;
  }

  let {
    open = $bindable(false),
    /** Owned by the caller, because the caller owns the scope this text is
     *  labelled with and decides what happens to it when that scope changes. */
    text = $bindable(""),
    scopeLabel = null,
    disabled = false,
    title = m.ai_builder_change_request_title(),
    example = m.ai_builder_change_request_example(),
    placeholder = m.ai_builder_change_request_placeholder(),
    hint = m.ai_builder_change_request_hint(),
    onclearscope,
    onopen,
    onsend
  }: Props = $props();

  let textarea = $state<HTMLTextAreaElement | null>(null);

  const canSend = $derived(!disabled && text.trim().length > 0);

  // The caller opens the box in the same tick, so the textarea does not exist
  // yet when this runs.
  export async function focusInput() {
    await tick();
    textarea?.focus();
    const end = text.length;
    textarea?.setSelectionRange(end, end);
  }

  function send() {
    if (!canSend) return;
    onsend(text.trim());
    text = "";
  }

  // Enter writes a newline; the plan is rewritten only on a deliberate chord.
  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      send();
    }
  }
</script>

<div class="border-default bg-primary overflow-hidden rounded-xl border">
  {#if open}
    <div class="px-[1.125rem] pt-3.5 pb-3">
      <div class="mb-2.5 flex flex-wrap items-center gap-2.5">
        <span class="text-primary text-[0.84375rem] font-semibold">{title}</span>
        {#if scopeLabel}
          <span
            class="bg-accent-dimmer text-accent-stronger inline-flex h-[1.625rem] items-center gap-1.5 rounded-full pr-1 pl-2.5 text-xs font-semibold"
          >
            {scopeLabel}
            <Button
              variant="ghost"
              size="icon-xs"
              class="hover:bg-accent-default/15 size-5 rounded-full"
              aria-label={m.ai_builder_change_request_clear_scope()}
              onclick={onclearscope}
            >
              <IconX class="size-3" />
            </Button>
          </span>
        {/if}
        <Button
          variant="ghost"
          size="xs"
          class="text-secondary hover:text-primary ml-auto"
          onclick={() => (open = false)}
        >
          {m.ai_builder_change_request_close()}
        </Button>
      </div>
      <Textarea
        bind:ref={textarea}
        bind:value={text}
        rows={2}
        {disabled}
        aria-label={m.ai_builder_change_request_textarea_label()}
        {placeholder}
        class="resize-y text-[0.84375rem] leading-relaxed"
        onkeydown={handleKeydown}
      />
      <div class="mt-2.5 flex flex-wrap items-center gap-2.5">
        <span class="text-secondary text-xs text-pretty">{hint}</span>
        <Button size="sm" class="ml-auto max-sm:w-full" disabled={!canSend} onclick={send}>
          {m.ai_builder_send()}
        </Button>
      </div>
    </div>
  {:else}
    <button
      type="button"
      class="hover:bg-secondary focus-visible:ring-accent-default/40 flex w-full flex-wrap items-center gap-2.5 px-[1.125rem] py-3.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
      onclick={() => {
        if (onopen) onopen();
        else open = true;
      }}
    >
      <span class="text-primary text-[0.84375rem] font-semibold">{title}</span>
      <span class="text-secondary text-xs max-sm:hidden">{example}</span>
      <span class="text-accent-stronger ml-auto text-xs font-semibold">
        {m.ai_builder_change_request_write()}
      </span>
    </button>
  {/if}
</div>
