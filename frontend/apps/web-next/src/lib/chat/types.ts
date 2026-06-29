import type { UIMessage } from "ai";
import type { Schema } from "@/lib/api/models";

/** Chat partner discriminator; mirrors the Svelte app's URL contract. */
export type ChatPartnerType = "default-assistant" | "assistant" | "group-chat";

export type ChatPartner = {
  type: ChatPartnerType;
  id: string;
  name: string;
  completionModel?: {
    id: string;
    name: string;
    token_limit?: number | null;
    vision?: boolean;
    reasoning?: boolean;
  } | null;
  /** Group chats: assistants available for @mentions. */
  mentionableAssistants?: { id: string; handle: string }[];
  /** Group chats: label which assistant answered. */
  showResponseLabel?: boolean;
};

export type CompletionModelInfo = {
  id: string;
  name: string;
  token_limit?: number | null;
  vision?: boolean | null;
  reasoning?: boolean | null;
} & Record<string, unknown>;

/** `data-session` part: v3's replacement for the v2 first_chunk metadata. */
export type SessionData = {
  session_id: string;
  completion_model: CompletionModelInfo | null;
  files: Schema<"FilePublic">[];
  web_search_references: { id: string; title: string; url: string }[];
  /** Group chats: which member assistant answered (null = none / clarification). */
  answering_assistant?: { id: string; handle: string } | null;
};

export type TokenUsageData = {
  prompt_tokens: number;
  completion_tokens: number;
  turn_tokens: number;
};

export type ToolCallInfo = {
  server_name: string;
  tool_name: string;
  arguments?: Record<string, unknown> | null;
  tool_call_id?: string | null;
  approved?: boolean | null;
  result_status?: string | null;
};

export type ToolApprovalData = {
  approval_id: string;
  status: "pending" | "timeout_denied";
  tools: ToolCallInfo[];
};

export type EneoDataParts = {
  session: SessionData;
  "token-usage": TokenUsageData;
  status: { status: string };
  "tool-approval": ToolApprovalData;
  error: { code?: number | null };
};

/** Message metadata used when mapping persisted sessions (not streamed). */
export type EneoMessageMetadata = {
  /** Uploaded attachments on a user message. */
  files?: Schema<"FilePublic">[];
  /** Generated files on a persisted assistant message (fetched on demand). */
  generatedFiles?: Schema<"FilePublic">[];
  webSearchReferences?: { id: string; title: string; url: string }[];
  tokens?: { prompt?: number | null; completion?: number | null };
  completionModel?: CompletionModelInfo | null;
  /** Group chats: which member assistant answered this message. */
  answeringAssistant?: { id: string; handle: string } | null;
};

export type EneoUIMessage = UIMessage<EneoMessageMetadata, EneoDataParts>;

/** The request body the /api/chat proxy forwards to the backend (v3). */
export type ConversationBody = {
  question: string;
  session_id?: string | null;
  assistant_id?: string | null;
  group_chat_id?: string | null;
  files: { id: string }[];
  tools?: { assistants: { id: string; handle: string }[] } | null;
  stream: true;
  use_web_search?: boolean;
  require_tool_approval?: boolean;
};
