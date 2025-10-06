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

  // Separate tracking for text and file tokens to prevent race conditions
  #textTokensApprox = $state<number>(0);
  #fileTokensCache = $state<number>(0);
  #lastCalculatedText = "";
  #lastCalculatedAttachmentIds = new Set<string>();

  // Track current state to avoid closure issues
  #currentText = "";
  #currentAttachmentIdString = "";

  // Learn token density from API responses for better approximations
  #learnedCharsPerToken = 4.0; // Default approximation, will be refined by API responses

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
      this.#textTokensApprox = 0;
      this.#fileTokensCache = 0;
      return;
    }

    // Store current text to avoid closure issues
    this.#currentText = text;

    // --- IMMEDIATE UPDATE FOR RESPONSIVE UI ---
    // Use learned token density for better approximations
    this.#textTokensApprox = Math.ceil(text.length / this.#learnedCharsPerToken);

    // Create a stable string representation of attachment IDs for comparison
    const attachmentIds = attachments.map(a => a.id).filter(Boolean);
    const attachmentIdString = attachmentIds.sort().join(',');

    // Check if attachments have actually changed based on ID string
    const attachmentsChanged = attachmentIdString !== this.#currentAttachmentIdString;

    // If attachments changed, reset file token cache with rough estimate
    if (attachmentsChanged) {
      this.#fileTokensCache = attachments.length * 1000; // Rough estimate until API returns
      this.#currentAttachmentIdString = attachmentIdString;
      this.#lastCalculatedAttachmentIds = new Set(attachmentIds);
    }

    // Immediately update with text approximation + cached file tokens
    this.newPromptTokens = this.#textTokensApprox + this.#fileTokensCache;

    // If no input at all, reset everything
    if (text.trim().length === 0 && attachments.length === 0) {
      this.newPromptTokens = 0;
      this.#textTokensApprox = 0;
      this.#fileTokensCache = 0;
      this.#lastCalculatedText = "";
      this.#lastCalculatedAttachmentIds.clear();
      return;
    }

    // --- DEBOUNCED API CALL FOR ACCURACY ---
    if (this.#newPromptTokenTimer) {
      clearTimeout(this.#newPromptTokenTimer);
    }

    // Store the request identifiers to check for staleness later
    const requestText = text;
    const requestAttachmentIdString = attachmentIdString;

    this.#newPromptTokenTimer = setTimeout(async () => {
      try {
        // Check if this request is stale by comparing with CURRENT state (not closure)
        if (this.#currentText !== requestText || this.#currentAttachmentIdString !== requestAttachmentIdString) {
          return; // Silently skip stale requests
        }

        // Use the request attachment IDs that were captured at the time of the request
        const fileIds = requestAttachmentIdString.split(',').filter(Boolean);

        // Use the token-estimate endpoint
        // Truncate text to avoid URL length limits (keep under 6000 chars for safety)
        const MAX_TEXT_LENGTH = 6000;
        const truncatedText = text.length > MAX_TEXT_LENGTH
          ? text.substring(0, MAX_TEXT_LENGTH)
          : text;

        const response = await this.#intric.client.fetch("/api/v1/assistants/{id}/token-estimate", {
          method: "get",
          params: {
            path: { id: this.#chatPartner.id },
            query: {
              file_ids: fileIds.join(','),
              text: truncatedText
            }
          }
        });

        // Learn token density from API response and scale if needed
        let adjustedBreakdown = response?.breakdown;
        if (response?.breakdown) {
          const apiTextTokens = response.breakdown.text || 0;
          const apiTextLength = text.length > MAX_TEXT_LENGTH ? MAX_TEXT_LENGTH : text.length;

          // Update learned ratio from API response (with smoothing)
          if (apiTextTokens > 0 && apiTextLength > 0) {
            const newCharsPerToken = apiTextLength / apiTextTokens;
            // Smooth the learning: 80% old value, 20% new observation
            this.#learnedCharsPerToken = this.#learnedCharsPerToken * 0.8 + newCharsPerToken * 0.2;
          }

          // If text was truncated, scale up the token estimate proportionally
          if (text.length > MAX_TEXT_LENGTH) {
            const scaleFactor = text.length / MAX_TEXT_LENGTH;
            adjustedBreakdown = {
              ...response.breakdown,
              text: Math.ceil(apiTextTokens * scaleFactor)
            };
          }
        }

        // Double-check staleness after API returns using CURRENT state
        if (this.#currentText !== requestText || this.#currentAttachmentIdString !== requestAttachmentIdString) {
          return; // Silently skip stale responses
        }

        if (adjustedBreakdown) {
          const breakdown = adjustedBreakdown;

          // Update cached file tokens ONLY if we're still working with the same attachments
          this.#fileTokensCache = breakdown.files || 0;

          // Calculate total tokens from breakdown - this is the accurate count
          const totalNewTokens = (breakdown.prompt || 0) + (breakdown.text || 0) + (breakdown.files || 0);

          // Update the total with accurate API result
          this.newPromptTokens = totalNewTokens;

          // Store the text that was calculated
          this.#lastCalculatedText = requestText;
        }
      } catch (error) {
        console.error('[ChatService] Token calculation failed, keeping approximation:', error);
        // Keep the current approximation on error
      }
    }, 300); // 300ms debounce for API accuracy
  }

  // Method to cleanly reset all token tracking
  resetNewPromptTokens() {
    this.newPromptTokens = 0;
    this.#textTokensApprox = 0;
    this.#fileTokensCache = 0;
    this.#lastCalculatedText = "";
    this.#lastCalculatedAttachmentIds.clear();
    this.#currentText = "";
    this.#currentAttachmentIdString = "";
    // Keep learned ratio - it's useful across messages

    // Cancel any pending API calls
    if (this.#newPromptTokenTimer) {
      clearTimeout(this.#newPromptTokenTimer);
      this.#newPromptTokenTimer = null;
    }
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
