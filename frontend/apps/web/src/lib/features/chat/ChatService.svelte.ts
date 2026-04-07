import { browser } from "$app/environment";
import { PAGINATION } from "$lib/core/constants";
import { toastError } from "$lib/core/errors";
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
  type ConversationTools,
  type SSE
} from "@intric/intric-js";

export type PendingToolApproval = {
  approvalId: string;
  tools: SSE.ToolApprovalRequired["tools"];
};

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


  // Tool approval state
  pendingToolApproval = $state<PendingToolApproval | null>(null);

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
      },
      onNull: () => {
        this.currentConversation = emptyConversation();
      }
    });
  }

  newConversation() {
    this.currentConversation = emptyConversation();
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
      toastError(e);
      console.error(e);
    }
  }

  async loadConversation(conversation: { id: string }) {
    try {
      const loaded = await this.#intric.conversations.get(conversation);
      this.currentConversation = loaded;
      return loaded;
    } catch (e) {
      toastError(e);
      console.error(e);
    }
  }

  changeChatPartner(newPartner: ChatPartner) {
    const oldPartner = this.#chatPartner;
    this.#chatPartner = newPartner;

    if (oldPartner !== newPartner) {
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
      abortController?: AbortController
    ) => {
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
          callbacks: {
            onFirstChunk: (chunk) => {
              if (isStale()) return;
              // Add the message to the conversation only after backend confirms
              this.currentConversation.messages?.push(emptyMessage({ question }));
              ref = this.currentConversation.messages[this.currentConversation.messages?.length - 1];
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
            onImage: (image) => {
              if (!ref || isStale()) return;
              if (!ensureCurrentSession(image)) return;
              Object.assign(ref, image);
            },
            onIntricEvent: (event) => {
              if (isStale()) return;
              if (!ensureCurrentSession(event)) return;

              if (event.intric_event_type === "generating_image") {
                ref.generated_files.push({ id: "", name: "", mimetype: "", size: 0 });
              }
            },
            onToolCall: (event) => {
              ensureCurrentSession(event);
              // Store tool calls for rendering with translations
              // @ts-expect-error - mcp_tool_calls is a runtime property for streaming
              if (!ref.mcp_tool_calls) {
                // @ts-expect-error
                ref.mcp_tool_calls = [];
              }
              // Update existing tool calls or add new ones (avoid duplicates from approval flow)
              for (const tool of event.tools) {
                // @ts-expect-error
                const existingIndex = ref.mcp_tool_calls.findIndex(
                  (t: { tool_call_id?: string }) => t.tool_call_id && t.tool_call_id === tool.tool_call_id
                );
                if (existingIndex >= 0) {
                  // Update existing entry with approval status
                  // @ts-expect-error
                  ref.mcp_tool_calls[existingIndex] = { ...ref.mcp_tool_calls[existingIndex], ...tool };
                } else {
                  // @ts-expect-error
                  ref.mcp_tool_calls.push(tool);
                }
              }
            },
            onToolApprovalRequired: (event) => {
              ensureCurrentSession(event);
              // Add tools to the message so they display in the UI
              // @ts-expect-error - mcp_tool_calls is a runtime property for streaming
              if (!ref.mcp_tool_calls) {
                // @ts-expect-error
                ref.mcp_tool_calls = [];
              }
              // @ts-expect-error
              ref.mcp_tool_calls.push(...event.tools);
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
                  // @ts-expect-error
                  ref.mcp_tool_calls = [];
                }
                for (const tool of event.tools) {
                  // @ts-expect-error
                  const existingIndex = ref.mcp_tool_calls.findIndex(
                    (t: { tool_call_id?: string }) =>
                      t.tool_call_id && t.tool_call_id === tool.tool_call_id
                  );
                  if (existingIndex >= 0) {
                    // @ts-expect-error
                    ref.mcp_tool_calls[existingIndex] = {
                      // @ts-expect-error
                      ...ref.mcp_tool_calls[existingIndex],
                      ...tool
                    };
                  } else {
                    // @ts-expect-error
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
          // In that case nothing more to do, just return
          return;
        }

        // If the error happened before streaming started (ref is undefined),
        // no message was added to the conversation — just propagate the error
        // so ConversationInput can restore the user's input.
        if (!ref) {
          console.error(error);
          throw error;
        }

        // If streaming started but no content arrived yet, remove the empty message
        if (error instanceof IntricError && !ref.answer) {
          this.currentConversation.messages.pop();
          console.error(error);
          throw error;
        }

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
      console.warn('[ChatService] No pending tool approval to submit');
      return;
    }

    try {
      await this.#intric.conversations.approveTools({
        approvalId: this.pendingToolApproval.approvalId,
        decisions
      });
    } catch (error) {
      console.error('[ChatService] Failed to submit tool approval:', error);
      throw error;
    } finally {
      // Clear pending approval regardless of success/failure
      this.pendingToolApproval = null;
    }
  }

  // Helper to approve all pending tools
  async approveAllTools() {
    if (!this.pendingToolApproval) return;

    const decisions = this.pendingToolApproval.tools.map(tool => ({
      tool_call_id: tool.tool_call_id!,
      approved: true
    }));

    await this.submitToolApproval(decisions);
  }

  // Helper to reject all pending tools
  async rejectAllTools() {
    if (!this.pendingToolApproval) return;

    const decisions = this.pendingToolApproval.tools.map(tool => ({
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
      t => t.tool_call_id !== toolCallId
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
      t => t.tool_call_id !== toolCallId
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
