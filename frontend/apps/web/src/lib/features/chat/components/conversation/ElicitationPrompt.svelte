<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import { Check, CircleCheck, CircleX, MessageCircleQuestion } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { getChatService } from "../../ChatService.svelte";

  type Props = {
    message: string;
    // First string field in the requested schema, when the server asked for a
    // free-text answer (vs. an empty schema = pure confirm/decline).
    answerField: string | null;
    suggestions: string[];
    // Fixed choice list. `multiple` => checkboxes (joined on submit); otherwise
    // single-choice pills that submit on click.
    options: string[];
    multiple: boolean;
    // "inline" sits inside a tool-call card's content; "standalone" floats above
    // the chat input. Both render the same Alert; standalone just adds a margin.
    variant: "inline" | "standalone";
    // Interactive only while this is the live, pending elicitation.
    isActive: boolean;
    // Persisted outcome (inline/history only). When set and not "pending" we
    // render the calm summary instead of the interactive form.
    status?: "pending" | "answered" | "declined";
    answer?: string | null;
  };

  let {
    message,
    answerField,
    suggestions,
    options,
    multiple,
    variant,
    isActive,
    status,
    answer = null
  }: Props = $props();

  const chat = getChatService();
  let draft = $state("");
  let selected = $state<string[]>([]);

  function toggleOption(option: string, on: boolean) {
    selected = on ? [...new Set([...selected, option])] : selected.filter((o) => o !== option);
  }

  function submitSelections() {
    if (selected.length === 0) return;
    chat.submitElicitation("accept", selected.join(", "));
  }

  // The server message is a question followed by a short change summary; split
  // so the question reads as the title and the summary as a muted subline —
  // tighter than rendering the raw multi-line string.
  const lines = $derived(
    message
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
  );
  const title = $derived(lines[0] ?? message);
  const summary = $derived(lines.slice(1).join(" "));

  // shadcn's `default` button maps to eneo's accent (blue); the affirmative
  // action uses eneo's positive (green) tokens in a soft tonal treatment so it
  // reads as a confirm without the heavy dark-green fill.
  const confirmClass =
    "bg-positive-dimmer text-positive-stronger hover:bg-positive-dimmer/60 border-positive-stronger/25";
  const marginClass = $derived(variant === "standalone" ? "mb-1.5" : "");

  function submitDraft() {
    if (!draft.trim()) return;
    const value = draft;
    draft = "";
    chat.submitElicitation("accept", value);
  }
</script>

{#if isActive}
  <Alert.Root class="border-dimmer flex flex-col gap-2 {marginClass}">
    <div class="flex items-start gap-2">
      <MessageCircleQuestion class="text-muted-foreground mt-0.5 size-4 shrink-0" />
      <div class="min-w-0 flex-1">
        <p class="text-foreground text-sm font-medium">{title}</p>
        {#if summary}
          <p class="text-muted-foreground mt-0.5 text-xs">{summary}</p>
        {/if}
      </div>
    </div>

    {#if answerField && options.length > 0 && multiple}
      <!-- Multi-select: checkboxes joined into the answer on confirm. -->
      <div class="flex flex-col gap-2 pl-6">
        {#each options as option (option)}
          <label class="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              checked={selected.includes(option)}
              onCheckedChange={(v) => toggleOption(option, v === true)}
            />
            <span class="text-foreground">{option}</span>
          </label>
        {/each}
      </div>
      <div class="flex items-center justify-end gap-2">
        <Button variant="outline" size="sm" onclick={() => chat.submitElicitation("decline")}>
          {m.decline()}
        </Button>
        <Button
          size="sm"
          class={confirmClass}
          disabled={selected.length === 0}
          onclick={submitSelections}
        >
          <Check />
          {m.confirm()}
        </Button>
      </div>
    {:else if answerField && options.length > 0}
      <!-- Single choice: one-tap pills that submit immediately. -->
      <div class="flex flex-wrap gap-1.5 pl-6">
        {#each options as option (option)}
          <Button
            variant="outline"
            size="sm"
            class="rounded-full"
            onclick={() => chat.submitElicitation("accept", option)}
          >
            {option}
          </Button>
        {/each}
      </div>
      <div class="flex items-center justify-end">
        <Button variant="outline" size="sm" onclick={() => chat.submitElicitation("decline")}>
          {m.decline()}
        </Button>
      </div>
    {:else if answerField}
      <!-- Free text, optionally with quick-fill suggestion chips. -->
      {#if suggestions.length > 0}
        <div class="flex flex-wrap gap-1.5 pl-6">
          {#each suggestions as suggestion (suggestion)}
            <Button
              variant="outline"
              size="sm"
              class="rounded-full"
              onclick={() => chat.submitElicitation("accept", suggestion)}
            >
              {suggestion}
            </Button>
          {/each}
        </div>
      {/if}
      <div class="flex items-center gap-2 pl-6">
        <Input
          bind:value={draft}
          placeholder={m.elicitation_answer_placeholder()}
          class="flex-1"
          onkeydown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submitDraft();
            }
          }}
        />
        <Button variant="outline" size="sm" onclick={() => chat.submitElicitation("decline")}>
          {m.decline()}
        </Button>
        <Button size="sm" class={confirmClass} disabled={!draft.trim()} onclick={submitDraft}>
          <Check />
          {m.send()}
        </Button>
      </div>
    {:else}
      <div class="flex items-center justify-end gap-2">
        <Button variant="outline" size="sm" onclick={() => chat.submitElicitation("decline")}>
          {m.decline()}
        </Button>
        <Button size="sm" class={confirmClass} onclick={() => chat.submitElicitation("accept")}>
          <Check />
          {m.confirm()}
        </Button>
      </div>
    {/if}
  </Alert.Root>
{:else if status && status !== "pending"}
  <!-- Persisted outcome, shown after answering and on reloaded history. -->
  <Alert.Root class="border-dimmer flex flex-col gap-1 {marginClass}">
    <div class="flex items-start gap-2">
      {#if status === "declined"}
        <CircleX class="text-negative-default mt-0.5 size-4 shrink-0" />
      {:else}
        <CircleCheck class="text-positive-default mt-0.5 size-4 shrink-0" />
      {/if}
      <div class="min-w-0 flex-1">
        <p class="text-foreground text-sm">{title}</p>
        <p class="text-muted-foreground mt-0.5 text-xs">
          {#if status === "declined"}
            {m.decline()}
          {:else}
            {answer ?? (summary || m.confirm())}
          {/if}
        </p>
      </div>
    </div>
  </Alert.Root>
{/if}
