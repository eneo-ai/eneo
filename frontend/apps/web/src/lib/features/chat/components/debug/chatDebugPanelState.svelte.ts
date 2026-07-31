import type { ChatTurnDiagnostics, ConversationMessage } from "@eneo/eneo-js";
import { untrack } from "svelte";
import { SvelteMap } from "svelte/reactivity";
import type { ChatService } from "../../ChatService.svelte";
import {
  listPersistedDebugTurns,
  projectTurnDebugDetails,
  type DebugTurnOption,
  type TurnDebugDetails
} from "../../turnDebugProjection";

/**
 * Selection and loading state for the chat debug panel.
 *
 * The state lives outside the panel markup so the desktop sidebar and the
 * mobile sheet can present the same selection without resetting it when the
 * viewport crosses the breakpoint. Construct during component initialisation:
 * the constructor registers `$effect`s.
 */
export class ChatDebugPanelState {
  #chat: ChatService;

  selectedMessageId = $state("");
  diagnostics = $state<ChatTurnDiagnostics | null>(null);
  loading = $state(false);
  refreshing = $state(false);
  loadError = $state(false);
  #selectionTouched = $state(false);
  #previousContextKey = "";
  #lastRequestKey = "";
  #requestGeneration = 0;

  readonly messages: ConversationMessage[];
  readonly turns: DebugTurnOption[];
  readonly #contextKey: string;
  readonly liveTurnPending: boolean;
  readonly #turnById: SvelteMap<string, DebugTurnOption>;
  readonly #messageById: SvelteMap<string, ConversationMessage>;
  readonly selectedTurn: DebugTurnOption | null;
  readonly selectedMessage: ConversationMessage | null;
  readonly selectedTurnIndex: number;
  readonly turnDetails: TurnDebugDetails | null;

  constructor(chat: ChatService, isAvailable: () => boolean) {
    this.#chat = chat;

    this.messages = $derived(chat.currentConversation.messages ?? []);
    this.turns = $derived(
      listPersistedDebugTurns(this.messages, chat.pendingDiagnosticsMessageIds)
    );
    this.#contextKey = $derived(
      `${chat.partner.type}:${chat.partner.id}:${chat.currentConversation.id}`
    );
    this.liveTurnPending = $derived(
      chat.askQuestion.isLoading || chat.pendingDiagnosticsMessageIds.length > 0
    );
    this.#turnById = $derived.by(() => {
      const index = new SvelteMap<string, DebugTurnOption>();
      for (const turn of this.turns) index.set(turn.messageId, turn);
      return index;
    });
    this.#messageById = $derived.by(() => {
      const index = new SvelteMap<string, ConversationMessage>();
      for (const message of this.messages) {
        if (message.id) index.set(message.id, message);
      }
      return index;
    });
    this.selectedTurn = $derived(this.#turnById.get(this.selectedMessageId) ?? null);
    this.selectedMessage = $derived(this.#messageById.get(this.selectedMessageId) ?? null);
    this.selectedTurnIndex = $derived(
      this.turns.findIndex((turn) => turn.messageId === this.selectedMessageId)
    );
    this.turnDetails = $derived(
      this.selectedMessage
        ? projectTurnDebugDetails(
            this.selectedMessage,
            this.diagnostics?.skill_activation
              ? {
                  id: this.diagnostics.skill_activation.selected_model_id,
                  route: this.diagnostics.skill_activation.selected_model_route
                }
              : undefined
          )
        : null
    );

    $effect(() => {
      const nextContextKey = this.#contextKey;
      const canOpen = isAvailable();
      untrack(() => {
        if (!this.#previousContextKey) this.#previousContextKey = nextContextKey;
        if (!canOpen || this.#previousContextKey !== nextContextKey) {
          this.#previousContextKey = nextContextKey;
          this.reset();
          if (chat.debugPanelOpen) chat.setDebugPanelOpen(false);
        }
      });
    });

    $effect(() => {
      const open = chat.debugPanelOpen;
      const latest = this.turns.at(-1)?.messageId ?? "";
      const selectedStillExists = this.#turnById.has(this.selectedMessageId);
      untrack(() => {
        if (!open) return;
        if (!this.#selectionTouched || !selectedStillExists) {
          this.selectedMessageId = latest;
          this.#selectionTouched = false;
        }
      });
    });

    $effect(() => {
      const open = chat.debugPanelOpen;
      const sessionId = chat.currentConversation.id;
      const messageId = this.selectedMessageId;
      const key = `${this.#contextKey}:${messageId}`;
      if (open && sessionId && messageId) {
        untrack(() => void this.#loadDiagnostics(key, sessionId, messageId, false));
      }
    });
  }

  setOpen(open: boolean) {
    this.#chat.setDebugPanelOpen(open);
    if (!open) this.reset();
  }

  reset() {
    this.#requestGeneration += 1;
    this.#lastRequestKey = "";
    this.selectedMessageId = "";
    this.diagnostics = null;
    this.loading = false;
    this.refreshing = false;
    this.loadError = false;
    this.#selectionTouched = false;
  }

  selectTurn(messageId: string) {
    this.#selectionTouched = true;
    this.selectedMessageId = messageId;
  }

  stepTurn(offset: -1 | 1) {
    const target = this.turns[this.selectedTurnIndex + offset];
    if (target) this.selectTurn(target.messageId);
  }

  retryLoad(keepCurrent: boolean) {
    const sessionId = this.#chat.currentConversation.id;
    if (!sessionId || !this.selectedMessageId) return;
    const key = `${this.#contextKey}:${this.selectedMessageId}`;
    void this.#loadDiagnostics(key, sessionId, this.selectedMessageId, keepCurrent, true);
  }

  async #loadDiagnostics(
    key: string,
    sessionId: string,
    messageId: string,
    keepCurrent: boolean,
    force = false
  ) {
    if (!force && key === this.#lastRequestKey) return;
    this.#lastRequestKey = key;
    const generation = ++this.#requestGeneration;
    this.loadError = false;
    if (keepCurrent && this.diagnostics) {
      this.refreshing = true;
    } else {
      this.diagnostics = null;
      this.loading = true;
    }

    try {
      const result = await this.#chat.getTurnDiagnostics(sessionId, messageId);
      if (generation !== this.#requestGeneration || key !== this.#lastRequestKey) return;
      if (result.session_id !== sessionId || result.message_id !== messageId) {
        throw new Error("Turn diagnostics response did not match the selected turn");
      }
      this.diagnostics = result;
    } catch {
      if (generation !== this.#requestGeneration || key !== this.#lastRequestKey) return;
      if (!keepCurrent) this.diagnostics = null;
      this.loadError = true;
    } finally {
      if (generation === this.#requestGeneration && key === this.#lastRequestKey) {
        this.loading = false;
        this.refreshing = false;
      }
    }
  }
}
