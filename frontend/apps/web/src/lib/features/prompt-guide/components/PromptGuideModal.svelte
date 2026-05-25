<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { LoaderCircle, SendHorizontal, Sparkles } from "lucide-svelte";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { tick, untrack } from "svelte";

  type Turn = {
    role: "user" | "assistant";
    text: string;
    isStreaming: boolean;
  };

  type Props = {
    targetId: string;
    targetType: "assistant";
    onApply: (text: string) => void;
    open?: boolean;
  };

  let { targetId, targetType, onApply, open = $bindable(false) }: Props = $props();
  const intric = getIntric();

  let turns = $state<Turn[]>([]);
  let inputText = $state("");
  let runId = $state<string | null>(null);
  let isStreaming = $state(false);
  let errorMessage = $state<string | null>(null);
  let didApply = $state(false);
  let activeAbortController: AbortController | null = null;
  let inputElement = $state<HTMLTextAreaElement | null>(null);
  let conversationElement = $state<HTMLDivElement>();
  let wasOpen = false;

  const lastFinalAssistantText = $derived.by(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      const turn = turns[i];
      if (turn.role === "assistant" && !turn.isStreaming && turn.text.trim().length > 0) {
        return turn.text;
      }
    }
    return "";
  });

  const hasFinalAnswer = $derived(lastFinalAssistantText.length > 0);

  function resetState() {
    if (activeAbortController) {
      activeAbortController.abort();
      activeAbortController = null;
    }
    turns = [];
    inputText = "";
    runId = null;
    isStreaming = false;
    errorMessage = null;
    didApply = false;
  }

  async function abandonRunIfNeeded(runIdToAbandon: string) {
    try {
      await intric.helpAssistants.runs.setStatus({
        run_id: runIdToAbandon,
        status: "abandoned"
      });
    } catch {
      // Best-effort: ignore failures so close UX isn't blocked.
    }
  }

  // React only to open/close transitions; untrack the rest so streaming-state
  // changes don't re-trigger this effect.
  $effect(() => {
    const isOpen = open;
    untrack(() => {
      if (isOpen && !wasOpen) {
        resetState();
        void tick().then(() => inputElement?.focus());
      } else if (!isOpen && wasOpen) {
        const runIdToClose = runId;
        const applied = didApply;
        resetState();
        if (runIdToClose && !applied) {
          void abandonRunIfNeeded(runIdToClose);
        }
      }
      wasOpen = isOpen;
    });
  });

  async function sendQuestion() {
    const question = inputText.trim();
    if (!question || isStreaming) return;

    inputText = "";
    errorMessage = null;
    isStreaming = true;
    activeAbortController = new AbortController();
    const controller = activeAbortController;

    turns = [
      ...turns,
      { role: "user", text: question, isStreaming: false },
      { role: "assistant", text: "", isStreaming: true }
    ];
    const assistantTurnIndex = turns.length - 1;

    const onAnswer = (data: { run?: { id?: string }; answer?: string }) => {
      if (!runId && data.run?.id) {
        runId = data.run.id;
      }
      if (!data.answer) return;
      const next = [...turns];
      const existing = next[assistantTurnIndex];
      next[assistantTurnIndex] = {
        ...existing,
        text: existing.text + data.answer
      };
      turns = next;
      void tick().then(() => {
        if (conversationElement) {
          conversationElement.scrollTop = conversationElement.scrollHeight;
        }
      });
    };

    try {
      const result = runId
        ? await intric.helpAssistants.runs.continueTurn({
            run_id: runId,
            question,
            stream: true,
            onAnswer,
            abortController: controller
          })
        : await intric.helpAssistants.runs.start({
            kind: "prompt_guide",
            target_type: targetType,
            target_id: targetId,
            question,
            stream: true,
            onAnswer,
            abortController: controller
          });

      if (controller.signal.aborted) return;

      if (!runId && result?.run?.id) {
        runId = result.run.id;
      }

      const accumulated = result?.answer ?? "";
      const next = [...turns];
      const existing = next[assistantTurnIndex];
      next[assistantTurnIndex] = {
        role: "assistant",
        text: accumulated.length > 0 ? accumulated : existing.text,
        isStreaming: false
      };
      turns = next;
    } catch (err) {
      if (controller.signal.aborted) return;
      console.error("PromptGuide stream failed", err);
      errorMessage = m.prompt_guide_error_generic();
      const next = [...turns];
      next[assistantTurnIndex] = { ...next[assistantTurnIndex], isStreaming: false };
      turns = next;
    } finally {
      if (activeAbortController === controller) {
        activeAbortController = null;
        isStreaming = false;
      }
    }
  }

  function handleApply() {
    if (!hasFinalAnswer || isStreaming) return;
    didApply = true;
    onApply(lastFinalAssistantText);
    open = false;
  }

  function handleInputKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendQuestion();
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="flex max-h-[85vh] flex-col sm:max-w-2xl">
    <Dialog.Header>
      <Dialog.Title>{m.prompt_guide_dialog_title()}</Dialog.Title>
      <Dialog.Description>{m.prompt_guide_dialog_description()}</Dialog.Description>
    </Dialog.Header>

    <form
      class="flex items-end gap-2"
      onsubmit={(event) => {
        event.preventDefault();
        void sendQuestion();
      }}
    >
      <Textarea
        bind:ref={inputElement}
        bind:value={inputText}
        onkeydown={handleInputKeydown}
        rows={2}
        disabled={isStreaming}
        aria-label={m.prompt_guide_dialog_title()}
        placeholder={m.prompt_guide_dialog_description()}
        class="max-h-40 min-h-16 flex-1 resize-none"
      />
      <Button
        type="submit"
        size="icon"
        aria-label={m.prompt_guide_button()}
        disabled={isStreaming || inputText.trim().length === 0}
      >
        {#if isStreaming}
          <LoaderCircle class="animate-spin" />
        {:else}
          <SendHorizontal />
        {/if}
      </Button>
    </form>

    <div
      bind:this={conversationElement}
      class="border-default bg-subtle min-h-48 flex-1 overflow-y-auto rounded-lg border p-4"
      aria-live="polite"
      aria-busy={isStreaming}
      aria-label={m.prompt_guide_streaming_announcement()}
    >
      {#if turns.length === 0}
        <div
          class="text-muted flex h-full flex-col items-center justify-center gap-2 text-center text-sm"
          role="status"
        >
          <Sparkles class="text-primary size-6 opacity-60" aria-hidden="true" />
          <p>{m.prompt_guide_dialog_description()}</p>
        </div>
      {:else}
        <ul class="flex flex-col gap-4">
          {#each turns as turn, index (index)}
            <li class="flex flex-col gap-1">
              {#if turn.role === "user"}
                <span class="text-muted text-xs font-medium tracking-wide uppercase">{m.you()}</span
                >
                <div
                  class="border-default bg-background rounded-md border px-3 py-2 text-sm whitespace-pre-wrap"
                >
                  {turn.text}
                </div>
              {:else}
                <span
                  class="text-muted flex items-center gap-1 text-xs font-medium tracking-wide uppercase"
                >
                  <Sparkles class="text-primary size-3" aria-hidden="true" />
                  {m.prompt_guide_dialog_title()}
                </span>
                <div class="text-default px-1 py-1 text-sm">
                  {#if turn.isStreaming && turn.text.length === 0}
                    <div class="text-muted flex items-center gap-2" role="status">
                      <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
                      <span>{m.prompt_guide_loading_message()}</span>
                    </div>
                  {:else}
                    <div class="whitespace-pre-wrap">{turn.text}</div>
                    {#if turn.isStreaming}
                      <span class="sr-only">{m.prompt_guide_streaming_announcement()}</span>
                    {/if}
                  {/if}
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    {#if errorMessage}
      <div
        role="alert"
        class="border-caution bg-caution text-caution rounded-md border px-3 py-2 text-sm"
      >
        {errorMessage}
      </div>
    {/if}

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.prompt_guide_cancel_button()}</Button>
        {/snippet}
      </Dialog.Close>
      {#if hasFinalAnswer}
        <Button onclick={handleApply} disabled={isStreaming}>
          {m.prompt_guide_apply_button()}
        </Button>
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
