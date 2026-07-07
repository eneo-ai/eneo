import type { UIMessage } from "ai";
import type { Schema } from "@/lib/api/models";

/** Chat partner discriminator; mirrors the Svelte app's URL contract. */
export type ChatPartnerType = "default-assistant" | "assistant" | "group-chat";

export type ChatPartner = {
  type: ChatPartnerType;
  id: string;
  name: string;
  allowedAttachments?: Schema<"FileRestrictions"> | null;
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
  /** MCP servers that can be toggled for this partner when no policy overrides them. */
  mcpServers?: Schema<"MCPServerPublicDict">[];
  /** Personal-assistant governance hints, including enforced MCP defaults. */
  effectiveConfig?: Schema<"EffectiveConfigPublic"> | null;
  /** Whether the partner exposes the conversation insights tab. */
  insightEnabled?: boolean;
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
  mcp_tool_references?: Schema<"McpToolReferencePublic">[];
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
  title?: string | null;
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
  "mcp-tool-references": { mcp_tool_references: Schema<"McpToolReferencePublic">[] };
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
  mcpToolReferences?: Schema<"McpToolReferencePublic">[];
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
  disabled_mcp_server_ids?: string[];
};
