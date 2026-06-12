import { browser } from "$app/environment";
import { PAGINATION } from "$lib/core/constants";
import { toastError } from "$lib/core/errors";
import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
import { createClassContext } from "$lib/core/helpers/createClassContext";
import { waitFor } from "$lib/core/waitFor";
import { selectEffectiveChatModel } from "$lib/features/chat/selectEffectiveChatModel";
import {
  type ConversationSparse,
  type Assistant,
  type Conversation,
  type GroupChat,
  type Intric,
  type Paginated,
  type UploadedFile,
  type ConversationMessage,
  IntricError,
  type ConversationTools,
  type SSE
} from "@intric/intric-js";

export type PendingToolApproval = {
  approvalId: string;
  tools: SSE.ToolApprovalRequired["tools"];
};

export type ChatPartner = GroupChat | Assistant;
type SparseCompletionModel = NonNullable<Assistant["completion_model"]>;

export class ChatService {
  #chatPartner = $state<ChatPartner>() as ChatPartner; // Needs typecast to get rid of undefined
  partner = $derived(this.#chatPartner);
  hasCompletionModel = $derived.by(() => {
    const partner = this.#chatPartner;
    if (!partner) return false;
    if ("completion_model" in partner) return this.#partnerEffectiveModel() !== undefined;
    return "tools" in partner && partner.tools?.assistants?.length > 0;
  });
  #intric: Intric;
  currentConversation = $state<Conversation>(emptyConversation());
  totalConversations = $state<number>(0);
  loadedConversations = $state<ConversationSparse[]>([]);
  hasMoreConversations = $derived(this.loadedConversations.length < this.totalConversations);
  #nextCursor = $state<string | null>(null);

  // Tool approval state
  pendingToolApproval = $state<PendingToolApproval | null>(null);

  // Context-window usage for the most recent turn. Split into input vs output
  // so the bar can show what was sent to the LLM (system + MCP + RAG + history
  // + question, lumped together in the provider's prompt_tokens) separately
  // from what the model returned. Updated live via SSE token_usage and seeded
  // from the last persisted message on conversation load.
  lockedInputTokens = $state<number>(0);
  lockedOutputTokens = $state<number>(0);
  contextTokens = $derived(this.lockedInputTokens + this.lockedOutputTokens);

  // Cumulative tokens billed over the entire conversation. Each turn re-sends
  // the full prompt (system + RAG + history), so per-message prompt_tokens
  // already include everything sent that turn; summing across messages gives
  // the true running spend, which grows roughly linearly with turn count even
  // when the per-turn snapshot looks flat. This is the cost-side view that
  // complements the headroom-side view shown on the bar itself.
  cumulativeTokens = $derived.by(() => {
    const messages = this.currentConversation?.messages;
    if (!messages?.length) return 0;
    let total = 0;
    for (const msg of messages) {
      total += msg.num_tokens_question ?? 0;
      total += msg.num_tokens_answer ?? 0;
    }
    return total;
  });
  turnCount = $derived(this.currentConversation?.messages?.length ?? 0);
  averageTokensPerTurn = $derived(
    this.turnCount > 0 ? Math.round(this.cumulativeTokens / this.turnCount) : 0
  );

  // Forward-looking estimate from the backend preflight endpoint. Set by the
  // input component as the user types (debounced). Cleared on send and on
  // conversation/partner switch. The total tokens this pending message will
  // add equals `pendingInputTokens + pendingFileTokens`.
  pendingInputTokens = $state<number>(0);
  pendingFileTokens = $state<number>(0);
  pendingModelName = $state<string>("");
  pendingContextWindow = $state<number>(0);
  #preflightDebounce: ReturnType<typeof setTimeout> | null = null;
  #preflightGen = 0;
  // Resolution order for the active model's context window:
  //   1. preflight (server-resolved current model, set while composing)
  //   2. for a single assistant, the partner's own model — it is global and
  //      authoritative for the next turn, so it must win over history (opening
  //      an old conversation must reflect the model that will actually answer,
  //      i.e. what the picker shows, not whatever model answered last time)
  //   3. the most recent message's model — only meaningful for group chats,
  //      where the active model varies per turn
  contextLimit = $derived<number>(
    this.pendingContextWindow ||
      this.#partnerModelTokenLimit() ||
      this.#latestMessageTokenLimit() ||
      0
  );

  // The name of the model that will answer the next turn. Single source of
  // truth for any "active model" label (e.g. the context bar) so it can never
  // disagree with contextLimit — same precedence: live preflight, then the
  // single assistant's own (global) model, then the latest message's model
  // for group chats where the active model varies per turn.
  activeModelName = $derived<string>(
    this.pendingModelName || this.#partnerModelName() || this.#latestMessageModelName() || ""
  );

  // Single source of truth for "the next message would overflow context".
  // Both the input (disable Send) and the usage bar (turn red) read from
  // here so the two surfaces can't disagree.
  willExceedContext = $derived<boolean>(
    this.contextLimit > 0 &&
      this.contextTokens + this.pendingInputTokens + this.pendingFileTokens > this.contextLimit
  );

  // The current partner's effective model — set only for single assistants
  // (group chats carry no single model, so this is undefined and the caller
  // falls back to the latest-message model). Mirrors backend governance
  // resolution: keep an allowed current model, otherwise use policy default,
  // then the first allowed model.
  #partnerEffectiveModel(): SparseCompletionModel | undefined {
    const partner = this.#chatPartner;
    if (!partner || !("completion_model" in partner)) return undefined;

    return selectEffectiveChatModel(partner.completion_model, partner.effective_config);
  }

  #partnerModelTokenLimit(): number | undefined {
    return this.#partnerEffectiveModel()?.token_limit ?? undefined;
  }

  #partnerModelName(): string | undefined {
    return this.#partnerEffectiveModel()?.name ?? undefined;
  }

  #latestMessageTokenLimit(): number | undefined {
    const messages = this.currentConversation?.messages;
    if (!messages?.length) return undefined;
    for (let i = messages.length - 1; i >= 0; i--) {
      const limit = messages[i].completion_model?.token_limit;
      if (limit) return limit;
    }
    return undefined;
  }

  #latestMessageModelName(): string | undefined {
    const messages = this.currentConversation?.messages;
    if (!messages?.length) return undefined;
    for (let i = messages.length - 1; i >= 0; i--) {
      const name = messages[i].completion_model?.name;
      if (name) return name;
    }
    return undefined;
  }

  // Streaming buffer for smoother text rendering (rAF-based for frame alignment)
  #streamBuffer = "";
  // Reasoning deltas share the same frame-aligned flush loop as answer text —
  // thinking-heavy models emit hundreds of deltas/sec, so appending each one
  // straight to reactive state would re-render the trace per token.
  #reasoningBuffer = "";
  #streamAnimationFrame: number | null = null;
  #lastFlushTime = 0;
  #streamRef: ConversationMessage | null = null;
  #streamFlushInterval = 33; // ~30fps target, imperceptible delay but smoother rendering
  #streamGen = 0;
  #producerFlushThreshold = 2048; // Safety flush for background tabs or fast streams

  constructor(data: Parameters<typeof this.init>[0]) {
    this.#intric = data.intric;
    this.init(data);
  }

  init(data: {
    intric: Intric;
    chatPartner: ChatPartner;
    initialConversation?: Promise<Conversation | null> | Conversation | null;
    initialHistory?: Promise<Paginated<ConversationSparse>> | Paginated<ConversationSparse>;
  }) {
    this.#chatPartner = data.chatPartner;

    waitFor(data.initialHistory, {
      onLoaded: (initialHistory) => {
        this.loadedConversations = initialHistory.items;
        this.totalConversations = initialHistory.total_count;
        this.#nextCursor = initialHistory.next_cursor ?? null;
      }
    });

    waitFor(data.initialConversation, {
      onLoaded: (initialConversation) => {
        this.currentConversation = initialConversation;
        this.#seedLockedFromHistory();
        this.#clearPreflight();
      },
      onNull: () => {
        this.currentConversation = emptyConversation();
        this.#resetLocked();
        this.#clearPreflight();
      }
    });
  }

  newConversation() {
    this.currentConversation = emptyConversation();
    this.#resetLocked();
    this.#clearPreflight();
  }

  #seedLockedFromHistory() {
    const messages = this.currentConversation?.messages;
    if (!messages?.length) {
      this.#resetLocked();
      return;
    }
    // Caveat: messages persisted before token measurement was added report
    // 0 here (backend stores NOT NULL int, no way to distinguish 0 from
    // "unmeasured"). Loading an old conversation will underreport actual
    // context fill — fixed when the user sends their next message and we
    // receive a fresh token_usage SSE event.
    const last = messages[messages.length - 1];
    this.lockedInputTokens = last.num_tokens_question ?? 0;
    this.lockedOutputTokens = last.num_tokens_answer ?? 0;
  }

  #resetLocked() {
    this.lockedInputTokens = 0;
    this.lockedOutputTokens = 0;
  }

  #clearPreflight() {
    this.#preflightGen += 1;
    if (this.#preflightDebounce) {
      clearTimeout(this.#preflightDebounce);
      this.#preflightDebounce = null;
    }
    this.pendingInputTokens = 0;
    this.pendingFileTokens = 0;
    this.pendingModelName = "";
    this.pendingContextWindow = 0;
  }

  /**
   * Estimate the token cost of the pending message. Debounced to avoid
   * spamming the backend on every keystroke. Race-safe via generation
   * counter — only the latest in-flight call wins.
   */
  requestPreflight(question: string, fileIds: string[], tools?: ConversationTools, delayMs = 400) {
    if (this.#preflightDebounce) {
      clearTimeout(this.#preflightDebounce);
    }

    if (!question && fileIds.length === 0) {
      this.#clearPreflight();
      return;
    }

    const gen = ++this.#preflightGen;
    const partnerAtStart = this.#chatPartner;
    const conversationAtStart = this.currentConversation;

    this.#preflightDebounce = setTimeout(async () => {
      try {
        const res = await this.#intric.conversations.preflight({
          chatPartner: partnerAtStart,
          conversation: conversationAtStart.id ? { id: conversationAtStart.id } : undefined,
          question,
          files: fileIds.map((id) => ({ id })),
          tools
        });

        // Discard if a newer request started or the user switched context
        if (gen !== this.#preflightGen) return;
        if (this.#chatPartner !== partnerAtStart) return;
        if (this.currentConversation.id !== conversationAtStart.id) return;

        this.pendingInputTokens = res.input_tokens;
        this.pendingFileTokens = res.file_tokens;
        this.pendingModelName = res.model_name;
        this.pendingContextWindow = res.context_window;
      } catch {
        // Silent failure — preflight is best-effort, not a blocker
        if (gen === this.#preflightGen) {
          this.pendingInputTokens = 0;
          this.pendingFileTokens = 0;
          this.pendingModelName = "";
          this.pendingContextWindow = 0;
        }
      }
    }, delayMs);
  }

  // RAF-based flush loop for smooth frame-aligned rendering
  #flushLoop = (timestamp: number) => {
    if (!this.#streamRef) return;

    const elapsed = timestamp - this.#lastFlushTime;

    // Flush answer and reasoning together when enough time has passed
    if (elapsed >= this.#streamFlushInterval && (this.#streamBuffer || this.#reasoningBuffer)) {
      if (this.#streamBuffer) {
        this.#streamRef.answer += this.#streamBuffer;
        this.#streamBuffer = "";
      }
      if (this.#reasoningBuffer) {
        this.#appendReasoning(this.#streamRef, this.#reasoningBuffer);
        this.#reasoningBuffer = "";
      }
      this.#lastFlushTime = timestamp;
    }

    // Continue the loop if we still have an active stream
    if (this.#streamRef) {
      this.#streamAnimationFrame = requestAnimationFrame(this.#flushLoop);
    }
  };

  #appendReasoning(ref: ConversationMessage, text: string) {
    // `reasoning` is a runtime-only streaming property on the message.
    (ref as { reasoning?: string }).reasoning =
      ((ref as { reasoning?: string }).reasoning ?? "") + text;
  }

  // Start the buffering loop for a message
  #startStreamBuffering(ref: ConversationMessage) {
    // If already streaming to this ref, just return
    if (this.#streamRef === ref) return;

    this.#streamRef = ref;
    this.#lastFlushTime = performance.now();

    // Cancel any existing loop
    if (this.#streamAnimationFrame) {
      cancelAnimationFrame(this.#streamAnimationFrame);
    }

    this.#streamAnimationFrame = requestAnimationFrame(this.#flushLoop);
  }

  // Force flush any remaining buffer (call when stream ends)
  #finalizeStream() {
    if (this.#streamAnimationFrame) {
      cancelAnimationFrame(this.#streamAnimationFrame);
      this.#streamAnimationFrame = null;
    }

    // Flush any remaining content
    if (this.#streamRef) {
      if (this.#streamBuffer) {
        this.#streamRef.answer += this.#streamBuffer;
        this.#streamBuffer = "";
      }
      if (this.#reasoningBuffer) {
        this.#appendReasoning(this.#streamRef, this.#reasoningBuffer);
        this.#reasoningBuffer = "";
      }
    }

    this.#streamRef = null;
  }

  async loadConversations(args?: { limit?: number; reset?: boolean }) {
    try {
      if (args?.reset) {
        this.#nextCursor = null;
      }
      const response = await this.#intric.conversations.list({
        chatPartner: this.#chatPartner,
        pagination: {
          limit: args?.limit ?? PAGINATION.PAGE_SIZE,
          cursor: this.#nextCursor ?? undefined
        }
      });

      if (args?.reset) {
        this.loadedConversations = response.items;
      } else {
        this.loadedConversations.push(...response.items);
      }

      this.#nextCursor = response.next_cursor ?? null;
      this.totalConversations = response.total_count;
      return response;
    } catch (error) {
      console.error("Error loading pagination", error);
    }
  }

  async loadMoreConversations(args?: { limit?: number }) {
    return this.loadConversations(args);
  }

  async reloadHistory() {
    return this.loadConversations({ reset: true });
  }

  async deleteConversation(conversation: { id: string }) {
    try {
      await this.#intric.conversations.delete(conversation);
      this.loadedConversations = this.loadedConversations.filter(
        ({ id }) => id !== conversation.id
      );
      if (this.currentConversation?.id === conversation.id) {
        this.newConversation();
      }
    } catch (e) {
      toastError(e);
      console.error(e);
    }
  }

  async renameConversation(conversation: { id: string }, name: string) {
    const trimmed = (name ?? "").trim();
    if (!trimmed) return;

    await this.#intric.conversations.rename(conversation, { name: trimmed });

    this.loadedConversations = this.loadedConversations.map((c) =>
      c.id === conversation.id ? { ...c, name: trimmed } : c
    );

    if (this.currentConversation?.id === conversation.id) {
      this.currentConversation.name = trimmed;
    }
  }

  async loadConversation(conversation: { id: string }) {
    try {
      const loaded = await this.#intric.conversations.get(conversation);
      this.currentConversation = loaded;
      this.#seedLockedFromHistory();
      this.#clearPreflight();
      return loaded;
    } catch (e) {
      toastError(e);
      console.error(e);
    }
  }

  changeChatPartner(newPartner: ChatPartner) {
    // Compare by id, not object identity: switching the personal assistant's
    // model replaces the partner object but keeps the same id, and that must
    // not wipe the open conversation — the model is global, so a switch just
    // changes which model answers the next turn. A different id is a genuine
    // partner switch and resets. (Comparing the $state proxy with !== also
    // trips Svelte's state_proxy_equality_mismatch warning.)
    const current = this.#chatPartner;
    const partnerChanged = current?.id !== newPartner?.id;
    if (
      !partnerChanged &&
      partnerRuntimeSignature(current) === partnerRuntimeSignature(newPartner)
    ) {
      return;
    }
    this.#chatPartner = newPartner;

    if (partnerChanged) {
      this.newConversation();
      this.reloadHistory();
    }
  }

  askQuestion = createAsyncState(
    async (
      question: string,
      attachments?: UploadedFile[],
      tools?: ConversationTools,
      useWebSearch?: boolean,
      requireToolApproval?: boolean,
      abortController?: AbortController,
      disabledMcpServerIds?: string[]
    ) => {
      // Clear preflight estimate — the message is leaving the input
      this.#clearPreflight();
      // End any previous stream loop/buffer
      this.#finalizeStream();
      const streamGen = ++this.#streamGen;
      let inrefBuffer = "";
      let ref: ReturnType<typeof emptyMessage> | undefined;
      const isStale = () => this.#streamGen !== streamGen;

      const ensureCurrentSession = (event: { session_id: string }) => {
        if (event.session_id !== this.currentConversation.id) {
          abortController?.abort();
          console.error(`cancelled streaming answer as session ${event.session_id} was changed.`);
          return false;
        }
        return true;
      };

      try {
        await this.#intric.conversations.ask({
          question,
          chatPartner: this.#chatPartner,
          conversation: { id: this.currentConversation.id },
          files: (attachments ?? []).map((fileRef) => ({ id: fileRef.id })),
          tools,
          abortController,
          useWebSearch,
          requireToolApproval,
          disabledMcpServerIds,
          callbacks: {
            onFirstChunk: (chunk) => {
              if (isStale()) return;
              // Add the message to the conversation only after backend confirms
              this.currentConversation.messages?.push(emptyMessage({ question }));
              ref =
                this.currentConversation.messages[this.currentConversation.messages?.length - 1];
              Object.assign(ref, chunk);
              this.currentConversation.id = chunk.session_id;
              this.currentConversation.name = question;
            },
            onText: (text) => {
              if (!ref) return;
              if (isStale()) {
                abortController?.abort();
                return;
              }

              if (!ensureCurrentSession(text)) return;

              // Handle inref buffering (existing logic)
              let textToAdd = text.answer;
              if (text.answer.includes("<") || inrefBuffer) {
                inrefBuffer += text.answer;
                if (isNotInref(inrefBuffer) || isCompleteInref(inrefBuffer)) {
                  textToAdd = inrefBuffer;
                  inrefBuffer = "";
                } else {
                  textToAdd = ""; // Wait for complete inref
                }
              }

              // Buffer text for frame-aligned rendering (reduces jitter)
              if (textToAdd) {
                if (!browser || typeof requestAnimationFrame !== "function") {
                  ref.answer += textToAdd;
                } else {
                  this.#streamBuffer += textToAdd;

                  if (this.#streamBuffer.length >= this.#producerFlushThreshold) {
                    ref.answer += this.#streamBuffer;
                    this.#streamBuffer = "";
                    this.#lastFlushTime = performance.now();
                  }

                  // Start or continue the rAF flush loop
                  this.#startStreamBuffering(ref);
                }
              }

              ref.references = text.references;
            },
            onReasoning: (event) => {
              if (!ref || isStale()) return;
              if (!ensureCurrentSession(event)) return;

              if (!browser || typeof requestAnimationFrame !== "function") {
                this.#appendReasoning(ref, event.reasoning);
                return;
              }

              // Buffer through the same frame-aligned loop as answer text.
              this.#reasoningBuffer += event.reasoning;
              if (this.#reasoningBuffer.length >= this.#producerFlushThreshold) {
                this.#appendReasoning(ref, this.#reasoningBuffer);
                this.#reasoningBuffer = "";
                this.#lastFlushTime = performance.now();
              }
              this.#startStreamBuffering(ref);
            },
            onImage: (image) => {
              if (!ref || isStale()) return;
              if (!ensureCurrentSession(image)) return;
              Object.assign(ref, image);
            },
            onIntricEvent: (event) => {
              if (isStale()) return;
              if (!ensureCurrentSession(event)) return;

              if (event.intric_event_type === "generating_image") {
                if (!ref) return;
                ref.generated_files.push({ id: "", name: "", mimetype: "", size: 0 });
              } else if (event.intric_event_type === "token_usage") {
                // The backend routes token_usage events through the same SSE
                // channel as intric events. Reflect them on the live message
                // so reload-from-history matches the in-memory state, then
                // expose the running context fill for the UI bar.
                const usage = (
                  event as unknown as {
                    usage?: { prompt_tokens: number; completion_tokens: number };
                  }
                ).usage;
                if (!usage) return;
                if (ref) {
                  ref.num_tokens_question = usage.prompt_tokens;
                  ref.num_tokens_answer = usage.completion_tokens;
                }
                this.lockedInputTokens = usage.prompt_tokens;
                this.lockedOutputTokens = usage.completion_tokens;
              }
            },
            onToolCall: (event) => {
              // Guard order matches the other SSE handlers: ref is only set
              // after onFirstChunk lands, so an early tool_call event would
              // otherwise crash trying to read mcp_tool_calls on undefined.
              if (!ref || isStale()) return;
              if (!ensureCurrentSession(event)) return;
              // Store tool calls for rendering with translations
              // @ts-expect-error - mcp_tool_calls is a runtime property for streaming
              if (!ref.mcp_tool_calls) {
                // @ts-expect-error - mcp_tool_calls is not in the static type
                ref.mcp_tool_calls = [];
              }
              // Update existing tool calls or add new ones (avoid duplicates from approval flow)
              for (const tool of event.tools as Array<{
                tool_call_id?: string;
                [key: string]: unknown;
              }>) {
                // @ts-expect-error - mcp_tool_calls is a runtime property
                const existingIndex = ref.mcp_tool_calls.findIndex(
                  (t: { tool_call_id?: string }) =>
                    t.tool_call_id && t.tool_call_id === tool.tool_call_id
                );
                if (existingIndex >= 0) {
                  // Update existing entry with approval status
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  const mcpCalls = (ref as any).mcp_tool_calls;
                  mcpCalls[existingIndex] = {
                    ...mcpCalls[existingIndex],
                    ...tool
                  };
                } else {
                  // @ts-expect-error - mcp_tool_calls is a runtime property
                  ref.mcp_tool_calls.push(tool);
                }
              }
            },
            onToolApprovalRequired: (event) => {
              if (isStale()) return;
              if (!ensureCurrentSession(event)) return;
              // tool_approval_required can race ahead of onFirstChunk when the
              // model returns a tool call before any text. Dropping the event
              // would leave pendingToolApproval unset, hiding the approve/deny
              // buttons forever while the backend keeps waiting. Materialise
              // the message here so the approval UI has something to attach to.
              if (!ref) {
                this.currentConversation.messages?.push(emptyMessage({ question }));
                ref =
                  this.currentConversation.messages[this.currentConversation.messages.length - 1];
                this.currentConversation.id = event.session_id;
              }
              // Add tools to the message so they display in the UI
              // @ts-expect-error - mcp_tool_calls is a runtime property for streaming
              if (!ref.mcp_tool_calls) {
                // @ts-expect-error - mcp_tool_calls is not in the static type
                ref.mcp_tool_calls = [];
              }
              // Merge by tool_call_id — a "pending" tool_call event may already
              // have registered these calls, and a blind push would duplicate them.
              for (const tool of event.tools as Array<{
                tool_call_id?: string;
                [key: string]: unknown;
              }>) {
                // @ts-expect-error - mcp_tool_calls is a runtime property
                const existingIndex = ref.mcp_tool_calls.findIndex(
                  (t: { tool_call_id?: string }) =>
                    t.tool_call_id && t.tool_call_id === tool.tool_call_id
                );
                if (existingIndex >= 0) {
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  const mcpCalls = (ref as any).mcp_tool_calls;
                  mcpCalls[existingIndex] = {
                    ...mcpCalls[existingIndex],
                    ...tool
                  };
                } else {
                  // @ts-expect-error - mcp_tool_calls is a runtime property
                  ref.mcp_tool_calls.push(tool);
                }
              }
              // Set pending approval state - UI will show inline approval buttons
              this.pendingToolApproval = {
                approvalId: event.approval_id,
                tools: event.tools
              };
            },
            onToolApprovalTimeout: (event) => {
              if (isStale()) return;
              if (!ensureCurrentSession(event)) return;
              // Backend timed out waiting for approval — clear pending state so the
              // approval UI no longer targets a dead approval_id, and merge the
              // timeout_denied status into the rendered tool calls so the user sees
              // what happened instead of stuck "Approve/Deny" buttons.
              if (
                this.pendingToolApproval &&
                this.pendingToolApproval.approvalId === event.approval_id
              ) {
                this.pendingToolApproval = null;
              }
              if (ref) {
                // @ts-expect-error - mcp_tool_calls is a runtime property for streaming
                if (!ref.mcp_tool_calls) {
                  // @ts-expect-error - mcp_tool_calls is a runtime property for streaming
                  ref.mcp_tool_calls = [];
                }
                for (const tool of event.tools) {
                  // @ts-expect-error - mcp_tool_calls is a runtime property for streaming
                  const existingIndex = ref.mcp_tool_calls.findIndex(
                    (t: { tool_call_id?: string }) =>
                      t.tool_call_id && t.tool_call_id === tool.tool_call_id
                  );
                  if (existingIndex >= 0) {
                    // @ts-expect-error - mcp_tool_calls is a runtime property for streaming
                    ref.mcp_tool_calls[existingIndex] = {
                      // @ts-expect-error - mcp_tool_calls is a runtime property for streaming
                      ...ref.mcp_tool_calls[existingIndex],
                      ...tool
                    };
                  } else {
                    // @ts-expect-error - mcp_tool_calls is a runtime property for streaming
                    ref.mcp_tool_calls.push(tool);
                  }
                }
              }
            }
          }
        });
      } catch (error) {
        if (isStale()) return;

        const streamAborted = error instanceof Error && error.message.includes("aborted");
        if (streamAborted) {
          // Backend persists the user's message before stream start and best-effort
          // saves a partial assistant reply on abort, so the conversation survives a
          // refresh. Falling through to reloadHistory() (below) syncs the sidebar with
          // the now-persisted state instead of leaving the new session invisible until
          // a manual reload.
        } else if (!ref) {
          // If the error happened before streaming started (ref is undefined),
          // no message was added to the conversation — just propagate the error
          // so ConversationInput can restore the user's input.
          console.error(error);
          throw error;
        } else if (error instanceof IntricError && !ref.answer) {
          // If streaming started but no content arrived yet, remove the empty message
          this.currentConversation.messages.pop();
          console.error(error);
          throw error;
        } else {
          // Error during streaming — show inline in the conversation
          let message = "We encountered an error processing your request.";
          if (error instanceof IntricError) {
            message += `\n\`\`\`\n${error.code}: "${error.getReadableMessage()}"\n\`\`\``;
          } else if (error instanceof Object && "message" in error && "name" in error) {
            message += `\n\`\`\`\n${error.name}: "${error.message}"\n\`\`\``;
          }

          this.currentConversation.messages[this.currentConversation.messages?.length - 1].answer =
            message;
          console.error(error);
        }
      } finally {
        if (this.#streamGen === streamGen) {
          if (ref && inrefBuffer) {
            ref.answer += inrefBuffer;
            inrefBuffer = "";
          }

          // Flush any remaining buffered content after stream completes
          this.#finalizeStream();
        }
      }

      if (this.#streamGen === streamGen) {
        this.reloadHistory();
      }

      // The $effect in constructor now handles automatic token calculation
    }
  );

  // Fetch prompt tokens and effective limit from backend.
  // When loading an existing conversation, approximate history tokens from message text.
  // Actual token counts are updated via SSE token_usage events after each LLM response.
  // Submit approval decisions for pending tool calls
  async submitToolApproval(decisions: Array<{ tool_call_id: string; approved: boolean }>) {
    if (!this.pendingToolApproval) {
      console.warn("[ChatService] No pending tool approval to submit");
      return;
    }

    try {
      await this.#intric.conversations.approveTools({
        approvalId: this.pendingToolApproval.approvalId,
        decisions
      });
    } catch (error) {
      console.error("[ChatService] Failed to submit tool approval:", error);
      throw error;
    } finally {
      // Clear pending approval regardless of success/failure
      this.pendingToolApproval = null;
    }
  }

  // Helper to approve all pending tools
  async approveAllTools() {
    if (!this.pendingToolApproval) return;

    const decisions = this.pendingToolApproval.tools.map((tool) => ({
      tool_call_id: tool.tool_call_id!,
      approved: true
    }));

    await this.submitToolApproval(decisions);
  }

  // Helper to reject all pending tools
  async rejectAllTools() {
    if (!this.pendingToolApproval) return;

    const decisions = this.pendingToolApproval.tools.map((tool) => ({
      tool_call_id: tool.tool_call_id!,
      approved: false
    }));

    await this.submitToolApproval(decisions);
  }

  // Approve a single tool and keep others pending
  async approveTool(toolCallId: string) {
    if (!this.pendingToolApproval) return;

    // Submit approval for this tool
    await this.#intric.conversations.approveTools({
      approvalId: this.pendingToolApproval.approvalId,
      decisions: [{ tool_call_id: toolCallId, approved: true }]
    });

    // Remove the approved tool from pending list
    const remainingTools = this.pendingToolApproval.tools.filter(
      (t) => t.tool_call_id !== toolCallId
    );

    if (remainingTools.length === 0) {
      // All tools processed, clear pending state
      this.pendingToolApproval = null;
    } else {
      // Update pending tools
      this.pendingToolApproval = {
        ...this.pendingToolApproval,
        tools: remainingTools
      };
    }
  }

  // Deny a single tool and keep others pending
  async denyTool(toolCallId: string) {
    if (!this.pendingToolApproval) return;

    // Submit denial for this tool
    await this.#intric.conversations.approveTools({
      approvalId: this.pendingToolApproval.approvalId,
      decisions: [{ tool_call_id: toolCallId, approved: false }]
    });

    // Remove the denied tool from pending list
    const remainingTools = this.pendingToolApproval.tools.filter(
      (t) => t.tool_call_id !== toolCallId
    );

    if (remainingTools.length === 0) {
      // All tools processed, clear pending state
      this.pendingToolApproval = null;
    } else {
      // Update pending tools
      this.pendingToolApproval = {
        ...this.pendingToolApproval,
        tools: remainingTools
      };
    }
  }
}

export const [getChatService, initChatService] = createClassContext("Chat service", ChatService);

function partnerRuntimeSignature(partner: ChatPartner | undefined) {
  if (!partner) return "";

  if ("completion_model" in partner) {
    const effectiveConfig = partner.effective_config;
    return JSON.stringify({
      id: partner.id,
      type: partner.type,
      name: partner.name,
      completion_model_id: partner.completion_model?.id ?? null,
      models_enforced: effectiveConfig?.models_enforced ?? false,
      default_model_id: effectiveConfig?.default_model?.id ?? null,
      locked_model_id: effectiveConfig?.locked_model?.id ?? null,
      available_model_ids: effectiveConfig?.available_models.map((model) => model.id) ?? [],
      // Include the MCP and prompt dimensions: a policy edit that touches only
      // these (same id + model) must still replace the partner, or the composer
      // keeps listing stale MCP servers / a stale enforced-prompt state.
      mcp_enforced: effectiveConfig?.mcp_enforced ?? false,
      available_mcp_server_ids:
        effectiveConfig?.available_mcp_servers?.map((server) => server.id) ?? [],
      default_disabled_mcp_server_ids: effectiveConfig?.default_disabled_mcp_server_ids ?? [],
      prompt_locked: effectiveConfig?.prompt_locked ?? false
    });
  }

  return JSON.stringify({
    id: partner.id,
    type: partner.type,
    name: partner.name,
    assistant_ids: partner.tools?.assistants.map((assistant) => assistant.id) ?? []
  });
}

function emptyMessage(partial?: Partial<ConversationMessage>): ConversationMessage {
  return {
    generated_files: [],
    question: "",
    answer: "",
    references: [],
    files: [],
    web_search_references: [],
    tools: {
      assistants: []
    },
    tool_calls: [],
    num_tokens_question: 0,
    num_tokens_answer: 0,
    ...partial
  };
}

function emptyConversation(): Conversation {
  return {
    id: "",
    name: "New conversation",
    messages: []
  };
}

const couldBeInref = (buffer: string): boolean => {
  // We assume that "<" can be anywhere in the buffer, but that there can only be one
  const start = buffer.indexOf("<");
  if (start === -1) return false;

  const tag = "<inref";
  const max = Math.min(tag.length, buffer.length - start);
  return buffer.slice(start, start + max) === tag.slice(0, max);
};
const isNotInref = (buffer: string): boolean => !couldBeInref(buffer);
const isCompleteInref = (buffer: string): boolean => {
  if (!couldBeInref(buffer)) return false;
  const start = buffer.indexOf("<");
  return buffer.indexOf(">", start) !== -1;
};
