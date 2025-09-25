import { browser } from "$app/environment";
import { PAGINATION } from "$lib/core/constants";
import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
import { createClassContext } from "$lib/core/helpers/createClassContext";
import { waitFor } from "$lib/core/waitFor";
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
  type ConversationTools
} from "@intric/intric-js";

export type ChatPartner = GroupChat | Assistant;

export class ChatService {
  #chatPartner = $state<ChatPartner>() as ChatPartner; // Needs typecast to get rid of undefined
  partner = $derived(this.#chatPartner);
  #intric: Intric;
  currentConversation = $state<Conversation>(emptyConversation());
  totalConversations = $state<number>(0);
  loadedConversations = $state<ConversationSparse[]>([]);
  hasMoreConversations = $derived(this.loadedConversations.length < this.totalConversations);
  #nextCursor = $state<string | null>(null);

  // Track total tokens used in the current conversation
  historyTokens = $state<number>(0);

  // Track tokens for the message being composed
  newPromptTokens = $state<number>(0);

  // Debounce timer for token calculations
  #tokenCalculationTimer: ReturnType<typeof setTimeout> | null = null;

  // Debounce timer for new prompt token calculations
  #newPromptTokenTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(data: Parameters<typeof this.init>[0]) {
    this.#intric = data.intric;
    this.init(data);

    // Automatically calculate history tokens when conversation changes
    $effect(() => {
      // This will automatically run whenever currentConversation or its messages change.
      // The calculateHistoryTokens method is already debounced, so this is safe.
      if (this.currentConversation?.messages?.length > 0) {
        this.calculateHistoryTokens();
      }
    });
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

        // Initialize token count if the conversation has a total_history_tokens field
        // This would come from backend when loading existing conversations
        if ((initialConversation as any)?.total_history_tokens) {
          this.historyTokens = (initialConversation as any).total_history_tokens;
        } else {
          // Calculate tokens for the loaded conversation
          this.calculateHistoryTokens();
        }
      },
      onNull: () => {
        this.currentConversation = emptyConversation();
        this.historyTokens = 0;
      }
    });
  }

  newConversation() {
    this.currentConversation = emptyConversation();
    // Reset token counters for new conversation
    this.historyTokens = 0;
    this.newPromptTokens = 0;
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
      if (browser) alert(`Error while deleting conversation with id ${conversation.id}`);
      console.error(e);
    }
  }

  async loadConversation(conversation: { id: string }) {
    try {
      const loaded = await this.#intric.conversations.get(conversation);
      this.currentConversation = loaded;

      // Initialize token count if the conversation has a total_history_tokens field
      // This would come from backend when loading existing conversations
      if ((loaded as any)?.total_history_tokens) {
        this.historyTokens = (loaded as any).total_history_tokens;
      } else {
        // Calculate tokens for the loaded conversation using the token-estimate endpoint
        this.calculateHistoryTokens();
      }
      return loaded;
    } catch (e) {
      if (browser) alert(`Error while loading conversation with id ${conversation.id}`);
      console.error(e);
    }
  }

  changeChatPartner(newPartner: ChatPartner) {
    const oldPartner = this.#chatPartner;
    this.#chatPartner = newPartner;

    if (oldPartner !== newPartner) {
      this.newConversation();
      this.reloadHistory();
      // Also reset new prompt tokens when partner changes
      this.newPromptTokens = 0;
    }
  }

  askQuestion = createAsyncState(
    async (
      question: string,
      attachments?: UploadedFile[],
      tools?: ConversationTools,
      useWebSearch?: boolean,
      abortController?: AbortController
    ) => {
      this.currentConversation.messages?.push(emptyMessage({ question }));

      const ensureCurrentSession = (event: { session_id: string }) => {
        if (event.session_id !== this.currentConversation.id) {
          abortController?.abort();
          console.error(`cancelled streaming answer as session ${event.session_id} was changed.`);
        }
      };

      try {
        let buffer = "";
        const ref =
          this.currentConversation.messages[this.currentConversation.messages?.length - 1];

        await this.#intric.conversations.ask({
          question,
          chatPartner: this.#chatPartner,
          conversation: { id: this.currentConversation.id },
          files: (attachments ?? []).map((fileRef) => ({ id: fileRef.id })),
          tools,
          abortController,
          useWebSearch,
          callbacks: {
            onFirstChunk: (chunk) => {
              Object.assign(ref, chunk);
              this.currentConversation.id = chunk.session_id;
              this.currentConversation.name = question;
            },
            onText: (text) => {
              ensureCurrentSession(text);
              if (text.answer.includes("<") || buffer) {
                buffer += text.answer;
                if (isNotInref(buffer) || isCompleteInref(buffer)) {
                  ref.answer += buffer;
                  buffer = "";
                }
              } else {
                ref.answer += text.answer;
              }
              ref.references = text.references;
            },
            onImage: (image) => {
              ensureCurrentSession(image);
              Object.assign(ref, image);
            },
            onIntricEvent: (event) => {
              ensureCurrentSession(event);

              // Debug logging for token-related events only
              if ((event as any).usage || event.intric_event_type === "token_usage") {
                console.log('[ChatService] Received potential token event:', {
                  eventType: event.intric_event_type,
                  hasUsage: !!(event as any).usage,
                  turnTokens: (event as any).usage?.turn_tokens,
                  fullEvent: event
                });
              }

              if (event.intric_event_type === "generating_image") {
                ref.generated_files.push({ id: "", name: "", mimetype: "", size: 0 });
              }

              // Handle token usage events from backend
              // The backend should send token count for this conversational turn
              if ((event as any).usage?.turn_tokens) {
                const turnTokens = (event as any).usage.turn_tokens;
                const oldTokens = this.historyTokens;
                this.historyTokens += turnTokens;
                console.log('[ChatService] ✅ TOKEN UPDATE RECEIVED:', {
                  turnTokens,
                  oldTotal: oldTokens,
                  newTotal: this.historyTokens
                });
              } else if (event.intric_event_type === "token_usage") {
                // Also check for a dedicated token_usage event type
                console.log('[ChatService] Received token_usage event but no turn_tokens found:', event);
              }
            }
          }
        });
      } catch (error) {
        const streamAborted = error instanceof Error && error.message.includes("aborted");
        if (streamAborted) {
          // In that case nothing more to do, just return
          return;
        }

        let message = "We encountered an error processing your request.";
        if (error instanceof IntricError) {
          message += `\n\`\`\`\n${error.code}: "${error.getReadableMessage()}"\n\`\`\``;
        } else if (error instanceof Object && "message" in error && "name" in error) {
          message += `\n\`\`\`\n$"${error.name}: error.message}"\n\`\`\``;
        }

        this.currentConversation.messages[this.currentConversation.messages?.length - 1].answer =
          message;
        console.error(error);
      }

      this.reloadHistory();

      // The $effect in constructor now handles automatic token calculation
    }
  );

  // New method to calculate tokens for the entire conversation history
  async calculateHistoryTokens() {
    // Don't calculate if no partner or messages
    if (!this.#chatPartner?.id || !this.currentConversation?.messages?.length) {
      return;
    }

    // Cancel any pending calculation
    if (this.#tokenCalculationTimer) {
      clearTimeout(this.#tokenCalculationTimer);
    }

    // Debounce the calculation
    this.#tokenCalculationTimer = setTimeout(async () => {
      try {
        // Combine all message content (questions and answers)
        const fullText = this.currentConversation.messages
          .map(msg => {
            let text = '';
            if (msg.question) text += msg.question + '\n';
            if (msg.answer) text += msg.answer + '\n';
            return text;
          })
          .join('\n');

        // Get file IDs from all messages
        const fileIds = this.currentConversation.messages
          .flatMap(msg => msg.files || [])
          .filter(file => file.id)
          .map(file => file.id);


        // Use the token-estimate endpoint
        const response = await this.#intric.client.fetch("/api/v1/assistants/{id}/token-estimate", {
          method: "get",
          params: {
            path: { id: this.#chatPartner.id },
            query: {
              file_ids: fileIds.join(','),
              text: fullText
            }
          }
        });

        if (response) {
          // Calculate total tokens from breakdown
          // The response has: breakdown.prompt + breakdown.text + breakdown.files
          const breakdown = response.breakdown || {};
          const totalTokens = (breakdown.prompt || 0) + (breakdown.text || 0) + (breakdown.files || 0);

          const oldTokens = this.historyTokens;
          this.historyTokens = totalTokens;

          console.log(
            `[ChatService] Token usage: ${totalTokens.toLocaleString()} tokens ` +
            `(text: ${breakdown.text || 0}, files: ${breakdown.files || 0}, prompt: ${breakdown.prompt || 0})`
          );
        }
      } catch (error) {
        console.error('[ChatService] Token calculation failed, using fallback');
        // Fallback to character-based approximation
        const fallbackTokens = Math.ceil(
          this.currentConversation.messages
            .map(msg => (msg.question || '').length + (msg.answer || '').length)
            .reduce((a, b) => a + b, 0) / 4
        );
        this.historyTokens = fallbackTokens;
      }
    }, 500); // 500ms debounce
  }

  // New method to calculate tokens for the message being composed
  async calculateNewPromptTokens(text: string, attachments: { id: string; size?: number }[]) {
    if (!this.#chatPartner?.id) {
      this.newPromptTokens = 0;
      return;
    }

    // --- IMMEDIATE UPDATE FOR RESPONSIVE UI ---
    // Provide instant approximation for typed text (1 token ≈ 4 characters)
    const textTokensApproximation = Math.ceil(text.length / 4);

    // Store the last known file token count to preserve it while typing
    const currentFileTokens = this.newPromptTokens > textTokensApproximation
      ? this.newPromptTokens - Math.ceil(text.length / 4)
      : 0;

    // Immediately update with text approximation
    if (text.length > 0 || attachments.length === 0) {
      // If we have text or no attachments, update immediately
      this.newPromptTokens = textTokensApproximation + (attachments.length > 0 ? currentFileTokens : 0);
    }

    // If no input at all, reset immediately
    if (text.trim().length === 0 && attachments.length === 0) {
      this.newPromptTokens = 0;
      return;
    }

    // --- DEBOUNCED API CALL FOR ACCURACY ---
    if (this.#newPromptTokenTimer) {
      clearTimeout(this.#newPromptTokenTimer);
    }

    this.#newPromptTokenTimer = setTimeout(async () => {
      try {
        const fileIds = attachments.filter(att => att.id).map(att => att.id);

        console.log('[ChatService] Making token-estimate API call:', {
          partnerId: this.#chatPartner.id,
          fileIds,
          textLength: text.length
        });

        // Use the token-estimate endpoint
        const response = await this.#intric.client.fetch("/api/v1/assistants/{id}/token-estimate", {
          method: "get",
          params: {
            path: { id: this.#chatPartner.id },
            query: {
              file_ids: fileIds.join(','),
              text: text
            }
          }
        });

        if (response?.breakdown) {
          const breakdown = response.breakdown;
          // Calculate total tokens from breakdown - this is the accurate count
          const totalNewTokens = (breakdown.prompt || 0) + (breakdown.text || 0) + (breakdown.files || 0);
          this.newPromptTokens = totalNewTokens;

          console.log(
            `[ChatService] ✅ Accurate token count: ${totalNewTokens.toLocaleString()} ` +
            `(text: ${breakdown.text || 0}, files: ${breakdown.files || 0}, prompt: ${breakdown.prompt || 0})`
          );
        } else {
          // Fallback if API response is malformed
          const fileTokens = attachments.length * 1000;
          this.newPromptTokens = textTokensApproximation + fileTokens;
        }
      } catch (error) {
        console.error('[ChatService] Token calculation failed, keeping approximation:', error);
        // Keep the immediate approximation on error
        const fileTokens = attachments.length * 1000;
        this.newPromptTokens = textTokensApproximation + fileTokens;
      }
    }, 300); // 300ms debounce for API accuracy
  }
}

export const [getChatService, initChatService] = createClassContext("Chat service", ChatService);

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
  return "<inref".startsWith(buffer.slice(buffer.indexOf("<"), 5));
};
const isNotInref = (buffer: string): boolean => !couldBeInref(buffer);
const isCompleteInref = (buffer: string): boolean => couldBeInref(buffer) && buffer.includes(">");
