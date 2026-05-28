<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<!--
  Premium Prompt Guide modal — shell.

  Owns the conversation state machine, the helper-run lifecycle, and the
  send/abort logic. Visual surfaces are delegated to focused children:

  - PromptGuideContextCard    "Your current instructions" collapsible.
  - PromptGuideConversation   transcript-style turn list + structured cards.
  - PromptGuideFinalCard      "Suggested instructions" + Copy + Apply.
  - PromptGuideInput          always-on textarea + Send (InputGroup primitive).

  Apply contract (critical test #4): `onApply(text)` only carries the
  extracted prompt out to the parent; the parent writes it into local editor
  state and the normal Save button persists it. There is no parallel
  apply-and-save path here.
-->

<script lang="ts">
  import { RefreshCw, Sparkles } from "lucide-svelte";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { tick, untrack } from "svelte";
  import { extractFinalPrompt } from "../extractFinalPrompt";
  import PromptGuideContextCard from "./PromptGuideContextCard.svelte";
  import PromptGuideConversation, { type Turn } from "./PromptGuideConversation.svelte";
  import PromptGuideFinalCard from "./PromptGuideFinalCard.svelte";
  import PromptGuideInput from "./PromptGuideInput.svelte";

  type Props = {
    targetId: string;
    targetType: "assistant";
    onApply: (text: string) => void;
    /**
     * The assistant's current prompt. When non-empty it is sent to the guide
     * on open so the conversation starts by analysing the existing
     * instructions; also shown as a collapsible context card. Captured at
     * open time so later edits don't restart the conversation.
     */
    targetPrompt?: string;
    /**
     * Whether the editor has unsaved manual changes to the prompt. When
     * true, Apply confirms before overwriting the textarea — the user has
     * pending edits that would otherwise be lost silently.
     */
    hasUnsavedPromptChanges?: boolean;
    open?: boolean;
    /**
     * Active helper-run id, exposed to the parent so the Apply handler can
     * mark the run completed. `null` until the first turn returns a run;
     * reset to `null` whenever the modal opens or closes.
     */
    runId?: string | null;
  };

  let {
    targetId,
    targetType,
    onApply,
    targetPrompt = "",
    hasUnsavedPromptChanges = false,
    open = $bindable(false),
    runId = $bindable<string | null>(null)
  }: Props = $props();
  const intric = getIntric();

  let turns = $state<Turn[]>([]);
  let inputText = $state("");
  let isStreaming = $state(false);
  let errorMessage = $state<string | null>(null);
  let didApply = $state(false);
  let capturedPrompt = $state("");
  let activeAbortController: AbortController | null = null;
  let lastSend = $state<{ question: string; showUserTurn: boolean } | null>(null);
  let inputElement = $state<HTMLTextAreaElement | null>(null);
  let wasOpen = false;

  // Apply only looks at the most recent completed assistant turn. The
  // structured-question parser reserves `eneo-question`-tagged blocks for
  // interactive cards, and `extractFinalPrompt` skips those — so a question
  // can never accidentally become the assistant's instructions.
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

  // React only to open/close transitions; untrack the rest so streaming
  // state changes don't re-trigger this effect.
  $effect(() => {
    const isOpen = open;
    untrack(() => {
      if (isOpen && !wasOpen) {
        resetState();
        capturedPrompt = (targetPrompt ?? "").trim();
        void tick().then(() => inputElement?.focus());
        // Auto-start: send the current prompt for analysis. The priming
        // message isn't shown as a user bubble — the guide's reply is the
        // first visible turn; the prompt itself lives in the context card.
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

  async function sendQuestion(rawQuestion: string, options?: { showUserTurn?: boolean }) {
    const showUserTurn = options?.showUserTurn ?? true;
    const question = rawQuestion.trim();
    if (!question || isStreaming) return;

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

    const onAnswer = (data: { run?: { id?: string }; answer?: string }) => {
      if (!runId && data.run?.id) {
        runId = data.run.id;
      }
      if (!data.answer) return;
      const next = [...turns];
      const existing = next[assistantTurnIndex];
      next[assistantTurnIndex] = { ...existing, text: existing.text + data.answer };
      turns = next;
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
        void tick().then(() => inputElement?.focus());
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

  function handleApply(text: string) {
    if (!text || isStreaming) return;
    // The textarea behind the dialog is unreachable while the modal is open,
    // so a stale `hasUnsavedPromptChanges = true` at apply time means the
    // user typed manually BEFORE opening the modal — Applying overwrites
    // their work, so confirm first.
    if (hasUnsavedPromptChanges && !window.confirm(m.prompt_guide_apply_overwrite_warning())) {
      return;
    }
    didApply = true;
    onApply(text);
    open = false;
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

    <PromptGuideContextCard text={capturedPrompt} />

    <PromptGuideConversation
      {turns}
      {isStreaming}
      hasCapturedPrompt={capturedPrompt.length > 0}
      onQuestionAnswer={(text) => void sendQuestion(text)}
    />

    {#if finalPrompt && !isStreaming}
      <PromptGuideFinalCard prompt={finalPrompt} disabled={isStreaming} onApply={handleApply} />
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

    <PromptGuideInput
      bind:value={inputText}
      bind:ref={inputElement}
      disabled={isStreaming}
      onSubmit={(text) => void sendQuestion(text)}
    />
  </Dialog.Content>
</Dialog.Root>
