<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import * as Sheet from "$lib/components/ui/sheet/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { ChatTurnDiagnostics, ConversationMessage } from "@eneo/eneo-js";
  import Bug from "@lucide/svelte/icons/bug";
  import Info from "@lucide/svelte/icons/info";
  import RotateCcw from "@lucide/svelte/icons/rotate-ccw";
  import X from "@lucide/svelte/icons/x";
  import { untrack } from "svelte";
  import { SvelteMap } from "svelte/reactivity";
  import type { ChatService } from "../../ChatService.svelte";
  import { listPersistedDebugTurns, projectTurnDebugDetails } from "../../turnDebugProjection";
  import SkillActivationDiagnostics from "./SkillActivationDiagnostics.svelte";
  import TurnDiagnosticsSummary from "./TurnDiagnosticsSummary.svelte";

  let { chat, available }: { chat: ChatService; available: boolean } = $props();

  let selectedMessageId = $state("");
  let diagnostics = $state<ChatTurnDiagnostics | null>(null);
  let loading = $state(false);
  let refreshing = $state(false);
  let loadError = $state(false);
  let selectionTouched = $state(false);
  let previousContextKey = "";
  let lastRequestKey = "";
  let requestGeneration = 0;

  const messages = $derived(chat.currentConversation.messages ?? []);
  const turns = $derived(listPersistedDebugTurns(messages, chat.askQuestion.isLoading));
  const contextKey = $derived(
    `${chat.partner.type}:${chat.partner.id}:${chat.currentConversation.id}`
  );
  const liveTurnPending = $derived(chat.askQuestion.isLoading && messages.length > 0);
  const turnById = $derived.by(() => {
    const index = new SvelteMap<string, (typeof turns)[number]>();
    for (const turn of turns) index.set(turn.messageId, turn);
    return index;
  });
  const messageById = $derived.by(() => {
    const index = new SvelteMap<string, ConversationMessage>();
    for (const message of messages) {
      if (message.id) index.set(message.id, message);
    }
    return index;
  });
  const selectedTurn = $derived(turnById.get(selectedMessageId) ?? null);
  const selectedMessage = $derived(messageById.get(selectedMessageId) ?? null);
  const turnDetails = $derived(selectedMessage ? projectTurnDebugDetails(selectedMessage) : null);
  const liveStatus = $derived(
    loading
      ? m.chat_debug_loading()
      : refreshing
        ? m.chat_debug_refreshing()
        : loadError
          ? m.chat_debug_load_error()
          : diagnostics
            ? m.chat_debug_loaded()
            : ""
  );

  $effect(() => {
    const nextContextKey = contextKey;
    const canOpen = available;
    untrack(() => {
      if (!previousContextKey) previousContextKey = nextContextKey;
      if (!canOpen || previousContextKey !== nextContextKey) {
        previousContextKey = nextContextKey;
        resetPanel();
        if (chat.debugPanelOpen) chat.setDebugPanelOpen(false);
      }
    });
  });

  $effect(() => {
    const open = chat.debugPanelOpen;
    const latest = turns.at(-1)?.messageId ?? "";
    const selectedStillExists = turnById.has(selectedMessageId);
    untrack(() => {
      if (!open) return;
      if (!selectionTouched || !selectedStillExists) {
        selectedMessageId = latest;
        selectionTouched = false;
      }
    });
  });

  $effect(() => {
    const open = chat.debugPanelOpen;
    const sessionId = chat.currentConversation.id;
    const messageId = selectedMessageId;
    const key = `${contextKey}:${messageId}`;
    if (open && sessionId && messageId) {
      untrack(() => void loadDiagnostics(key, sessionId, messageId, false));
    }
  });

  function setOpen(open: boolean) {
    chat.setDebugPanelOpen(open);
    if (!open) resetPanel();
  }

  function resetPanel() {
    requestGeneration += 1;
    lastRequestKey = "";
    selectedMessageId = "";
    diagnostics = null;
    loading = false;
    refreshing = false;
    loadError = false;
    selectionTouched = false;
  }

  function selectTurn(messageId: string) {
    selectionTouched = true;
    selectedMessageId = messageId;
  }

  async function loadDiagnostics(
    key: string,
    sessionId: string,
    messageId: string,
    keepCurrent: boolean,
    force = false
  ) {
    if (!force && key === lastRequestKey) return;
    lastRequestKey = key;
    const generation = ++requestGeneration;
    loadError = false;
    if (keepCurrent && diagnostics) {
      refreshing = true;
    } else {
      diagnostics = null;
      loading = true;
    }

    try {
      const result = await chat.getTurnDiagnostics(sessionId, messageId);
      if (generation !== requestGeneration || key !== lastRequestKey) return;
      if (result.session_id !== sessionId || result.message_id !== messageId) {
        throw new Error("Turn diagnostics response did not match the selected turn");
      }
      diagnostics = result;
    } catch {
      if (generation !== requestGeneration || key !== lastRequestKey) return;
      if (!keepCurrent) diagnostics = null;
      loadError = true;
    } finally {
      if (generation === requestGeneration && key === lastRequestKey) {
        loading = false;
        refreshing = false;
      }
    }
  }

  function retryLoad(keepCurrent: boolean) {
    const sessionId = chat.currentConversation.id;
    if (!sessionId || !selectedMessageId) return;
    const key = `${contextKey}:${selectedMessageId}`;
    void loadDiagnostics(key, sessionId, selectedMessageId, keepCurrent, true);
  }

  function turnLabel(turn: (typeof turns)[number]): string {
    return m.chat_debug_turn_option({
      number: String(turn.turnNumber),
      question: turn.questionExcerpt || m.chat_debug_empty_question()
    });
  }
</script>

{#if available}
  <Sheet.Root open={chat.debugPanelOpen} onOpenChange={setOpen}>
    <Sheet.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant={chat.debugPanelOpen ? "secondary" : "outline"}>
          <Bug data-icon="inline-start" aria-hidden="true" />
          {m.chat_debug_open()}
        </Button>
      {/snippet}
    </Sheet.Trigger>

    <Sheet.Content
      id="chat-debug-panel"
      class="w-full max-w-full gap-0 p-0 sm:max-w-[36rem]"
      showCloseButton={false}
    >
      <Sheet.Header class="border-border gap-1 border-b px-5 py-4 pr-14">
        <Sheet.Title class="flex items-center gap-2 text-base font-semibold">
          <Bug aria-hidden="true" />
          {m.chat_debug_title()}
        </Sheet.Title>
        <Sheet.Description class="max-w-[54ch] leading-5">
          {m.chat_debug_description()}
        </Sheet.Description>
        <Sheet.Close>
          {#snippet child({ props })}
            <Button
              {...props}
              class="absolute top-3 right-3"
              variant="ghost"
              size="icon-sm"
              aria-label={m.close()}
            >
              <X aria-hidden="true" />
            </Button>
          {/snippet}
        </Sheet.Close>
      </Sheet.Header>

      <p class="sr-only" role="status" aria-live="polite">{liveStatus}</p>

      <div class="border-border flex flex-col gap-2 border-b px-5 py-4">
        <label for="chat-debug-turn-select" class="text-xs font-medium">
          {m.chat_debug_select_turn()}
        </label>
        <div class="flex min-w-0 items-center gap-2">
          <Select.Root
            type="single"
            value={selectedMessageId}
            disabled={turns.length === 0}
            onValueChange={selectTurn}
          >
            <Select.Trigger id="chat-debug-turn-select" class="min-w-0 flex-1">
              <span data-slot="select-value" class="min-w-0 truncate">
                {selectedTurn ? turnLabel(selectedTurn) : m.chat_debug_select_turn_placeholder()}
              </span>
            </Select.Trigger>
            <Select.Content class="max-h-80 max-w-[calc(100vw-2rem)]">
              <Select.Group>
                <Select.Label>{m.chat_debug_available_turns()}</Select.Label>
                {#each turns as turn (turn.messageId)}
                  <Select.Item value={turn.messageId} label={turnLabel(turn)}>
                    <span class="max-w-[28rem] truncate">{turnLabel(turn)}</span>
                  </Select.Item>
                {/each}
              </Select.Group>
            </Select.Content>
          </Select.Root>
          {#if diagnostics}
            <Button
              variant="outline"
              size="icon"
              disabled={refreshing}
              aria-label={m.chat_debug_refresh()}
              onclick={() => retryLoad(true)}
            >
              <RotateCcw class={refreshing ? "animate-spin" : undefined} aria-hidden="true" />
            </Button>
          {/if}
        </div>
      </div>

      <div class="min-h-0 flex-1 overscroll-contain overflow-y-auto [scrollbar-gutter:stable]">
        {#if liveTurnPending}
          <div class="px-5 pt-5">
            <Alert.Root>
              <Info aria-hidden="true" />
              <Alert.Title>{m.chat_debug_live_turn_title()}</Alert.Title>
              <Alert.Description>{m.chat_debug_live_turn_description()}</Alert.Description>
            </Alert.Root>
          </div>
        {/if}

        {#if turns.length === 0 && !liveTurnPending}
          {@render EmptyState(m.chat_debug_no_turn_title(), m.chat_debug_no_turn_description())}
        {:else if turns.length === 0}
          {@render EmptyState(
            m.chat_debug_waiting_for_turn_title(),
            m.chat_debug_waiting_for_turn_description()
          )}
        {:else if loading}
          <div class="flex flex-col gap-4 p-5" aria-busy="true" aria-label={m.chat_debug_loading()}>
            <Skeleton class="h-24 w-full" />
            <Skeleton class="h-32 w-full" />
            <Skeleton class="h-20 w-full" />
          </div>
        {:else if loadError && !diagnostics}
          <div class="p-5">
            <Alert.Root variant="destructive">
              <Alert.Title>{m.chat_debug_unavailable_title()}</Alert.Title>
              <Alert.Description>{m.chat_debug_unavailable_description()}</Alert.Description>
              <Alert.Action>
                <Button variant="outline" size="sm" onclick={() => retryLoad(false)}>
                  <RotateCcw data-icon="inline-start" aria-hidden="true" />
                  {m.chat_debug_retry()}
                </Button>
              </Alert.Action>
            </Alert.Root>
          </div>
        {:else if diagnostics && turnDetails}
          {#if loadError}
            <div class="px-5 pt-5">
              <Alert.Root variant="destructive">
                <Alert.Title>{m.chat_debug_refresh_error_title()}</Alert.Title>
                <Alert.Description>{m.chat_debug_refresh_error_description()}</Alert.Description>
              </Alert.Root>
            </div>
          {/if}
          <TurnDiagnosticsSummary details={turnDetails} />
          {#if diagnostics.skill_activation}
            <SkillActivationDiagnostics evidence={diagnostics.skill_activation} />
          {:else}
            <Separator />
            <section
              class="flex flex-col gap-1 px-5 py-5"
              aria-labelledby="chat-debug-skill-activation"
            >
              <h2 id="chat-debug-skill-activation" class="text-sm font-semibold">
                {m.chat_debug_legacy_skills_title()}
              </h2>
              <p class="text-muted-foreground max-w-[65ch] text-sm leading-5">
                {m.chat_debug_legacy_skills_description()}
              </p>
            </section>
          {/if}
        {/if}
      </div>
    </Sheet.Content>
  </Sheet.Root>
{/if}

{#snippet EmptyState(title: string, description: string)}
  <div class="flex min-h-56 flex-col items-start justify-center gap-2 px-5 py-8">
    <h2 class="text-sm font-semibold">{title}</h2>
    <p class="text-muted-foreground max-w-[52ch] text-sm leading-5">{description}</p>
  </div>
{/snippet}
