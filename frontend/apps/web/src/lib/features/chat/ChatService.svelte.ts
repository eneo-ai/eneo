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
  hasCompletionModel = $derived(
    this.#chatPartner &&
    ('completion_model' in this.#chatPartner
      ? this.#chatPartner.completion_model !== null &&
        this.#chatPartner.completion_model !== undefined
      : 'tools' in this.#chatPartner &&
        this.#chatPartner.tools?.assistants?.length > 0)
  );
  #intric: Intric;
  currentConversation = $state<Conversation>(emptyConversation());
  totalConversations = $state<number>(0);
  loadedConversations = $state<ConversationSparse[]>([]);
  hasMoreConversations = $derived(this.loadedConversations.length < this.totalConversations);
  #nextCursor = $state<string | null>(null);

  // Track total tokens used in the current conversation
  historyTokens = $state<number>(0);

  // Track assistant prompt tokens separately so we only count them once
  promptTokens = $state<number>(0);

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

  // Cache token counts per file ID to avoid resets when adding/removing files
  #fileTokenMap = new Map<string, number>();

  // Debounce timer for token calculations
  #tokenCalculationTimer: ReturnType<typeof setTimeout> | null = null;

  // Debounce timer for new prompt token calculations
  #newPromptTokenTimer: ReturnType<typeof setTimeout> | null = null;

  // Streaming buffer for smoother text rendering (rAF-based for frame alignment)
  #streamBuffer = "";
  #streamAnimationFrame: number | null = null;
  #lastFlushTime = 0;
  #streamRef: ConversationMessage | null = null;
  #streamFlushInterval = 33; // ~30fps target, imperceptible delay but smoother rendering
  #streamGen = 0;
  #producerFlushThreshold = 2048; // Safety flush for background tabs or fast streams

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
    this.promptTokens = 0;
  }

  // RAF-based flush loop for smooth frame-aligned rendering
  #flushLoop = (timestamp: number) => {
    if (!this.#streamRef) return;

    const elapsed = timestamp - this.#lastFlushTime;

    // Flush if enough time has passed
    if (elapsed >= this.#streamFlushInterval && this.#streamBuffer) {
      this.#streamRef.answer += this.#streamBuffer;
      this.#streamBuffer = "";
      this.#lastFlushTime = timestamp;
    }

    // Continue the loop if we still have an active stream
    if (this.#streamRef) {
      this.#streamAnimationFrame = requestAnimationFrame(this.#flushLoop);
    }
  };

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
    if (this.#streamBuffer && this.#streamRef) {
      this.#streamRef.answer += this.#streamBuffer;
      this.#streamBuffer = "";
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
      this.promptTokens = 0;
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

      // End any previous stream loop/buffer
      this.#finalizeStream();
      const streamGen = ++this.#streamGen;
      let inrefBuffer = "";
      const ref =
        this.currentConversation.messages[this.currentConversation.messages?.length - 1];
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
          callbacks: {
            onFirstChunk: (chunk) => {
              if (isStale()) return;
              Object.assign(ref, chunk);
              this.currentConversation.id = chunk.session_id;
              this.currentConversation.name = question;
            },
            onText: (text) => {
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
            onImage: (image) => {
              if (isStale()) return;
              if (!ensureCurrentSession(image)) return;
              Object.assign(ref, image);
            },
            onIntricEvent: (event) => {
              if (isStale()) return;
              if (!ensureCurrentSession(event)) return;

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
        if (isStale()) return;

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
      } finally {
        if (this.#streamGen === streamGen) {
          if (inrefBuffer) {
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
          method: "post",
          params: {
            path: { id: this.#chatPartner.id }
          },
          requestBody: {
            "application/json": {
              text: fullText,
              file_ids: fileIds
            }
          }
        });

        if (response) {
          const breakdown = response.breakdown || {};
          const promptTokens = breakdown.prompt ?? this.promptTokens;
          const historyTokens = (breakdown.text || 0) + (breakdown.files || 0);

          this.promptTokens = promptTokens;
          this.historyTokens = historyTokens;

          console.log(
            `[ChatService] Token usage: ${(promptTokens + historyTokens).toLocaleString()} tokens ` +
            `(text: ${breakdown.text || 0}, files: ${breakdown.files || 0}, prompt: ${promptTokens})`
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

    // If attachments changed, recalculate file tokens from cached values
    if (attachmentsChanged) {
      const estimateTokensFromSize = (fileSize?: number | null) => {
        const fallbackSize = 100_000; // ~250 tokens fallback when size is unknown
        const size = fileSize && fileSize > 0 ? fileSize : fallbackSize;
        const bytesPerToken = 400; // generous average across supported formats
        return Math.ceil(size / bytesPerToken);
      };

      // Calculate total file tokens from cached per-file values
      let totalFileTokens = 0;
      for (const fileId of attachmentIds) {
        if (this.#fileTokenMap.has(fileId)) {
          // Use cached value for files we've seen before
          totalFileTokens += this.#fileTokenMap.get(fileId)!;
        } else {
          // Rough estimate for new files (will be updated by API)
          const attachment = attachments.find(file => file.id === fileId);
          const roughEstimate = estimateTokensFromSize(attachment?.size);
          this.#fileTokenMap.set(fileId, roughEstimate);
          totalFileTokens += roughEstimate;
        }
      }

      // Remove cached tokens for files that are no longer present
      const currentFileIdSet = new Set(attachmentIds);
      for (const cachedFileId of this.#fileTokenMap.keys()) {
        if (!currentFileIdSet.has(cachedFileId)) {
          this.#fileTokenMap.delete(cachedFileId);
        }
      }

      this.#fileTokensCache = totalFileTokens;
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
      this.#fileTokenMap.clear();
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

        const response = await this.#intric.client.fetch("/api/v1/assistants/{id}/token-estimate", {
          method: "post",
          params: {
            path: { id: this.#chatPartner.id }
          },
          requestBody: {
            "application/json": {
              text,
              file_ids: fileIds
            }
          }
        });

        if (response?.breakdown) {
          const apiTextTokens = response.breakdown.text || 0;
          const apiTextLength = text.length;

          if (apiTextTokens > 0 && apiTextLength > 0) {
            const newCharsPerToken = apiTextLength / apiTextTokens;
            this.#learnedCharsPerToken = this.#learnedCharsPerToken * 0.8 + newCharsPerToken * 0.2;
          }
        }

        // Double-check staleness after API returns using CURRENT state
        if (this.#currentText !== requestText || this.#currentAttachmentIdString !== requestAttachmentIdString) {
          return; // Silently skip stale responses
        }

        const breakdown = response?.breakdown;
        if (breakdown) {

          // Update per-file token cache with accurate values from API
          if (response?.breakdown?.file_details) {
            for (const [fileId, tokenCount] of Object.entries(response.breakdown.file_details)) {
              this.#fileTokenMap.set(fileId, tokenCount as number);
            }
          }

          // Update cached file tokens total
          this.#fileTokensCache = breakdown.files || 0;

          // Persist prompt tokens separately so we only count them once
          const promptTokens = breakdown.prompt ?? this.promptTokens;
          this.promptTokens = promptTokens;

          // Calculate total tokens from breakdown without the assistant prompt
          const totalNewTokens = (breakdown.text || 0) + (breakdown.files || 0);

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
    this.#fileTokenMap.clear();
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
