<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import {
    Check,
    ChevronDown,
    Copy,
    FileText,
    LoaderCircle,
    RefreshCw,
    SendHorizontal,
    Sparkles,
    User
  } from "lucide-svelte";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { tick, untrack } from "svelte";
  import { fade, slide } from "svelte/transition";
  import PromptGuideMarkdown from "./PromptGuideMarkdown.svelte";
  import { extractFinalPrompt } from "../extractFinalPrompt";

  type Turn = {
    role: "user" | "assistant";
    text: string;
    isStreaming: boolean;
  };

  type Props = {
    targetId: string;
    targetType: "assistant";
    onApply: (text: string) => void;
    /**
     * The assistant's current prompt. When non-empty it is sent to the guide on
     * open so the conversation starts by analysing the existing instructions
     * (PRD §10); also shown as a collapsible context card. Captured at open time
     * so later edits don't restart the conversation.
     */
    targetPrompt?: string;
    open?: boolean;
    /**
     * Active helper-run id, exposed to the parent so the Apply handler can mark
     * the run completed (PRD §10). `null` until the first turn returns a run;
     * reset to `null` whenever the modal opens or closes.
     */
    runId?: string | null;
  };

  let {
    targetId,
    targetType,
    onApply,
    targetPrompt = "",
    open = $bindable(false),
    runId = $bindable<string | null>(null)
  }: Props = $props();
  const intric = getIntric();

  let turns = $state<Turn[]>([]);
  let inputText = $state("");
  let isStreaming = $state(false);
  let errorMessage = $state<string | null>(null);
  let didApply = $state(false);
  let copied = $state(false);
  let contextOpen = $state(false);
  let capturedPrompt = $state("");
  let activeAbortController: AbortController | null = null;
  let lastSend = $state<{ question: string; showUserTurn: boolean } | null>(null);
  let inputElement = $state<HTMLTextAreaElement | null>(null);
  let conversationElement = $state<HTMLDivElement>();
  let wasOpen = false;

  // The guide reserves a fenced code block for its final prompt; that block —
  // not the whole reply — is what Apply writes, so a question never becomes the
  // instructions. Read from the latest completed assistant turn.
  const lastFinalAssistantText = $derived.by(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      const turn = turns[i];
      if (turn.role === "assistant" && !turn.isStreaming && turn.text.trim().length > 0) {
        return turn.text;
      }
    }
    return "";
  });
  const finalPrompt = $derived(extractFinalPrompt(lastFinalAssistantText));

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
    copied = false;
    contextOpen = false;
    lastSend = null;
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

  function buildPrimingQuestion(): string {
    return capturedPrompt.length > 0
      ? m.prompt_guide_priming_with_prompt({ prompt: capturedPrompt })
      : m.prompt_guide_priming_no_prompt();
  }

  // React only to open/close transitions; untrack the rest so streaming-state
  // changes don't re-trigger this effect.
  $effect(() => {
    const isOpen = open;
    untrack(() => {
      if (isOpen && !wasOpen) {
        resetState();
        capturedPrompt = (targetPrompt ?? "").trim();
        void tick().then(() => inputElement?.focus());
        // Auto-start: send the current prompt for analysis (PRD §10). The
        // priming message isn't shown as a user bubble — the guide's reply is
        // the first visible turn; the prompt itself lives in the context card.
        void sendQuestion(buildPrimingQuestion(), { showUserTurn: false });
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

  function scrollToBottom() {
    void tick().then(() => {
      if (conversationElement) {
        conversationElement.scrollTop = conversationElement.scrollHeight;
      }
    });
  }

  async function sendQuestion(rawQuestion: string, options?: { showUserTurn?: boolean }) {
    const showUserTurn = options?.showUserTurn ?? true;
    const question = rawQuestion.trim();
    if (!question || isStreaming) return;

    if (showUserTurn) inputText = "";
    lastSend = { question, showUserTurn };
    errorMessage = null;
    isStreaming = true;
    activeAbortController = new AbortController();
    const controller = activeAbortController;

    const pending = [...turns];
    if (showUserTurn) pending.push({ role: "user", text: question, isStreaming: false });
    pending.push({ role: "assistant", text: "", isStreaming: true });
    turns = pending;
    const assistantTurnIndex = turns.length - 1;
    scrollToBottom();

    const onAnswer = (data: { run?: { id?: string }; answer?: string }) => {
      if (!runId && data.run?.id) {
        runId = data.run.id;
      }
      if (!data.answer) return;
      const next = [...turns];
      const existing = next[assistantTurnIndex];
      next[assistantTurnIndex] = { ...existing, text: existing.text + data.answer };
      turns = next;
      scrollToBottom();
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
      scrollToBottom();
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

  function retryLast() {
    if (!lastSend || isStreaming) return;
    const { question, showUserTurn } = lastSend;
    // Drop the failed turn(s) from the last attempt, then re-run it verbatim.
    const removeCount = showUserTurn ? 2 : 1;
    turns = turns.slice(0, Math.max(0, turns.length - removeCount));
    errorMessage = null;
    void sendQuestion(question, { showUserTurn });
  }

  function handleApply() {
    if (!finalPrompt || isStreaming) return;
    didApply = true;
    onApply(finalPrompt);
    open = false;
  }

  async function copyFinalPrompt() {
    if (!finalPrompt) return;
    try {
      await navigator.clipboard.writeText(finalPrompt);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      // Clipboard can be unavailable (permissions / insecure context); ignore.
    }
  }

  function handleInputKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendQuestion(inputText);
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="flex max-h-[85vh] flex-col gap-3 sm:max-w-2xl">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2">
        <Sparkles class="text-primary size-5" aria-hidden="true" />
        {m.prompt_guide_dialog_title()}
      </Dialog.Title>
      <Dialog.Description>{m.prompt_guide_dialog_description()}</Dialog.Description>
    </Dialog.Header>

    {#if capturedPrompt}
      <div class="border-default bg-subtle overflow-hidden rounded-lg border">
        <button
          type="button"
          class="hover:bg-hover-dimmer flex w-full items-center gap-2 px-3 py-2 text-left transition-colors"
          aria-expanded={contextOpen}
          onclick={() => (contextOpen = !contextOpen)}
        >
          <FileText class="text-muted size-4 shrink-0" aria-hidden="true" />
          <span class="text-default flex-1 text-sm font-medium"
            >{m.prompt_guide_current_prompt_label()}</span
          >
          <ChevronDown
            class="text-muted size-4 shrink-0 transition-transform {contextOpen ? 'rotate-180' : ''}"
            aria-hidden="true"
          />
        </button>
        {#if contextOpen}
          <div class="border-default border-t px-3 py-2" transition:slide={{ duration: 150 }}>
            <p class="text-secondary max-h-32 overflow-y-auto text-xs whitespace-pre-wrap">
              {capturedPrompt}
            </p>
          </div>
        {/if}
      </div>
    {/if}

    <div
      bind:this={conversationElement}
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
        <ul class="flex flex-col gap-5">
          {#each turns as turn, index (index)}
            <li class="flex gap-3">
              <div
                class="bg-secondary grid size-7 shrink-0 place-items-center rounded-full"
                aria-hidden="true"
              >
                {#if turn.role === "assistant"}
                  <Sparkles class="text-primary size-3.5" />
                {:else}
                  <User class="text-muted size-3.5" />
                {/if}
              </div>
              <div class="min-w-0 flex-1 pt-0.5">
                <div class="text-muted mb-1 text-xs font-medium capitalize">
                  {turn.role === "assistant" ? m.prompt_guide_dialog_title() : m.you()}
                </div>
                {#if turn.role === "user"}
                  <div class="text-default text-sm break-words whitespace-pre-wrap">{turn.text}</div>
                {:else if turn.isStreaming && turn.text.length === 0}
                  <div class="text-muted flex items-center gap-2 text-sm" role="status">
                    <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
                    <span
                      >{index === 0 && capturedPrompt
                        ? m.prompt_guide_analyzing()
                        : m.prompt_guide_loading_message()}</span
                    >
                  </div>
                {:else}
                  <PromptGuideMarkdown source={turn.text} class="text-default" />
                  {#if turn.isStreaming}
                    <span class="sr-only">{m.prompt_guide_streaming_announcement()}</span>
                    <span class="bg-primary ml-0.5 inline-block h-4 w-0.5 animate-pulse align-middle"
                    ></span>
                  {/if}
                {/if}
              </div>
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    {#if finalPrompt && !isStreaming}
      <div
        class="border-default bg-subtle flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2.5"
        transition:fade={{ duration: 150 }}
      >
        <div class="bg-secondary grid size-8 shrink-0 place-items-center rounded-full">
          <Sparkles class="text-primary size-4" aria-hidden="true" />
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-default text-sm font-medium">{m.prompt_guide_final_prompt_label()}</div>
          <div class="text-muted text-xs">{m.prompt_guide_final_prompt_hint()}</div>
        </div>
        <Button variant="outline" size="sm" onclick={copyFinalPrompt}>
          {#if copied}
            <Check class="size-3.5" />
            {m.copied()}
          {:else}
            <Copy class="size-3.5" />
            {m.copy()}
          {/if}
        </Button>
        <Button size="sm" onclick={handleApply}>
          {m.prompt_guide_apply_button()}
        </Button>
      </div>
    {/if}

    {#if errorMessage}
      <div
        role="alert"
        class="border-caution bg-caution text-caution flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm"
      >
        <span class="flex-1">{errorMessage}</span>
        {#if lastSend}
          <Button variant="outline" size="sm" onclick={retryLast}>
            <RefreshCw class="size-3.5" />
            {m.prompt_guide_retry()}
          </Button>
        {/if}
      </div>
    {/if}

    <form
      class="flex items-end gap-2"
      onsubmit={(event) => {
        event.preventDefault();
        void sendQuestion(inputText);
      }}
    >
      <Textarea
        bind:ref={inputElement}
        bind:value={inputText}
        onkeydown={handleInputKeydown}
        rows={2}
        disabled={isStreaming}
        aria-label={m.prompt_guide_input_placeholder()}
        placeholder={m.prompt_guide_input_placeholder()}
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

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.prompt_guide_cancel_button()}</Button>
        {/snippet}
      </Dialog.Close>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
