import type { UIMessage } from "ai";
import type { Schema } from "@/lib/api/models";

/** Chat partner discriminator; mirrors the Svelte app's URL contract. */
export type ChatPartnerType = "default-assistant" | "assistant" | "group-chat";

/** A knowledge source attached to a partner (collection or crawled website). */
export type KnowledgeOrigin = { id: string; name: string; kind: "collection" | "website" };

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
  enabledCapabilities?: Schema<"AssistantPublic">["enabled_capabilities"];
  availableCapabilities?: Schema<"AssistantPublic">["available_capabilities"];
  /** Personal-assistant governance hints, including enforced MCP defaults. */
  effectiveConfig?: Schema<"EffectiveConfigPublic"> | null;
  /** Whether the partner exposes the conversation insights tab. */
  insightEnabled?: boolean;
  /** Short description shown on the start screen (assistants, group chats). */
  description?: string | null;
  /** Uploaded icon id (tile image), when the partner has one. */
  iconId?: string | null;
  /** Name of the space the partner lives in (header subtitle). */
  spaceName?: string | null;
  /** The space's security classification label, when it has one. */
  securityClassification?: string | null;
  /** Collections and websites the partner searches (named activity steps and sources). */
  knowledge?: KnowledgeOrigin[];
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
  "tool-approval": ToolApprovalData;
  error: { code?: number | null };
};

/** A rating of one answer: 1 good, -1 bad, null not rated. */
export type AnswerRating = 1 | -1 | null;

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
  /** When the message was created (ISO 8601), for the timestamp under answers. */
  createdAt?: string | null;
  /** A saved answer's rating by the conversation's owner. */
  feedback?: AnswerRating;
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
  disabled_capabilities?: Schema<"ConversationRequest">["disabled_capabilities"];
  require_tool_approval?: boolean;
  disabled_mcp_server_ids?: string[];
};
