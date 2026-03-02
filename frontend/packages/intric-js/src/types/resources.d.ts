import { components } from "./schema";

export type Assistant =
  | components["schemas"]["AssistantPublic"]
  | components["schemas"]["DefaultAssistant"];

export type AssistantSparse = Omit<components["schemas"]["AssistantSparse"], "user_id">;
export type AssistantResponse = Omit<
  components["schemas"]["AskResponse"],
  "session_id" | "references" | "tools"
> & {
  session_id?: string | undefined;
  id?: string | undefined | null;
  created_at?: string | null | undefined;
  tools?: components["schemas"]["UseTools"];
  references: Omit<components["schemas"]["InfoBlobAskAssistantPublic"], "score">[];
};
export type AssistantSession = components["schemas"]["SessionPublic"];
export type Service = components["schemas"]["ServicePublicWithUser"];
export type ServiceSparse = components["schemas"]["ServiceSparse"];
export type Group = Omit<
  components["schemas"]["GroupPublicWithMetadata"],
  "embedding_model" | "user"
> & {
  embedding_model?: components["schemas"]["EmbeddingModelSparse"] | null | undefined;
};
export type GroupSparse = components["schemas"]["GroupPublicWithMetadata"];
export type InfoBlob = Omit<components["schemas"]["InfoBlobPublic"], "text"> & {
  text?: string | undefined;
};
export type Widget = components["schemas"]["WidgetPublic"];
export type CompletionModel = components["schemas"]["CompletionModelPublic"];
export type EmbeddingModel = components["schemas"]["EmbeddingModelPublic"];
export type TranscriptionModel = components["schemas"]["TranscriptionModelPublic"];
export type SecurityClassification = components["schemas"]["SecurityClassificationPublic"];
export type Job = components["schemas"]["JobPublic"];
export type JobStatus = components["schemas"]["Status"];
export type Tenant = components["schemas"]["TenantPublic"];
export type ModelProviderPublic = components["schemas"]["ModelProviderPublic"];
export type AnalyticsData = components["schemas"]["MetadataStatistics"];
export type UserGroup = components["schemas"]["UserGroupPublic"];
export type User = components["schemas"]["UserAdminView"];
export type UserSparse = components["schemas"]["UserSparse"];
export type CurrentUser = components["schemas"]["UserPublic"];
export type Role = components["schemas"]["RolePublic"];
export type Permission = components["schemas"]["Permission"];
export type ResourcePermission = components["schemas"]["ResourcePermission"];
export type CrawlRun = components["schemas"]["CrawlRunPublic"];
export type Limits = components["schemas"]["Limits"];
export type UploadedFile = components["schemas"]["FilePublic"];
export type Website = components["schemas"]["WebsitePublic"];
export type Settings = components["schemas"]["SettingsPublic"];
export type WebsiteSparse = components["schemas"]["WebsiteSparse"];
export type Space = components["schemas"]["SpacePublic"];
export type SpaceSparse = components["schemas"]["SpaceSparse"];
export type Dashboard = components["schemas"]["Dashboard"];
export type Prompt = components["schemas"]["PromptPublic"];
export type PromptSparse = components["schemas"]["PromptSparse"];
export type IntricErrorCode = components["schemas"]["ErrorCodes"] | 0;
export type ApiKeyType = components["schemas"]["ApiKeyType"];
export type ApiKeyPermission = components["schemas"]["ApiKeyPermission"];
export type ApiKeyScopeType = components["schemas"]["ApiKeyScopeType"];
export type ApiKeyState = components["schemas"]["ApiKeyState"];
export type ApiKeyStateReasonCode = components["schemas"]["ApiKeyStateReasonCode"];
export type ResourcePermissionLevel = components["schemas"]["ResourcePermissionLevel"];
export type ResourcePermissions = components["schemas"]["ResourcePermissions"];
export type ApiKeyCreationConstraints = components["schemas"]["ApiKeyCreationConstraints"];
export type ApiKeyV2 = components["schemas"]["ApiKeyV2"];
export type ApiKeyCreateRequest = components["schemas"]["ApiKeyCreateRequest"];
export type ApiKeyUpdateRequest = components["schemas"]["ApiKeyUpdateRequest"];
export type ApiKeyStateChangeRequest = components["schemas"]["ApiKeyStateChangeRequest"];
export type ApiKeyCreatedResponse = components["schemas"]["ApiKeyCreatedResponse"];
export type ApiKeyPolicy = components["schemas"]["ApiKeyPolicyResponse"];
export type SuperApiKeyStatus = components["schemas"]["SuperApiKeyStatus"];

export type CursorPaginated<T> = {
  items: T[];
  total_count: number;
  limit?: number | null;
  next_cursor?: string | null;
  previous_cursor?: string | null;
};

export type ApiKeyListResponse = components["schemas"]["ApiKeyListResponse"];
export type ApiKeyAdminListResponse = components["schemas"]["CursorPaginatedResponse_ApiKeyV2_"];
export type App = components["schemas"]["AppPublic"];
export type AppSparse = components["schemas"]["AppSparse"];
export type AppRun = components["schemas"]["AppRunPublic"];
export type AppRunSparse = components["schemas"]["AppRunSparse"];
export type AppRunInput = components["schemas"]["AppRunInput"];
export type AssistantTemplate = components["schemas"]["AssistantTemplatePublic"];
export type AppTemplate = components["schemas"]["AppTemplatePublic"];
export type TemplateAdditionalField = components["schemas"]["AdditionalField"];
export type SpaceRole = components["schemas"]["SpaceRole"];
export type StorageSpaceList = components["schemas"]["StorageSpaceInfoModel"];
export type StorageUsageSummary = components["schemas"]["StorageModel"];
export type TokenUsageSummary = components["schemas"]["TokenUsageSummary"];
export type Integration = components["schemas"]["Integration"];
export type UserIntegration = components["schemas"]["UserIntegration"];
export type TenantIntegration = components["schemas"]["TenantIntegration"];
export type IntegrationKnowledge = components["schemas"]["IntegrationKnowledgePublic"];
export type IntegrationKnowledgePreview = components["schemas"]["IntegrationPreviewData"];
export type Conversation = components["schemas"]["SessionPublic"] & {
  messages: ConversationMessage[];
};
export type ConversationSparse = components["schemas"]["SessionMetadataPublic"];
export type ConversationMessage = components["schemas"]["Message"];
export type ConversationTools = components["schemas"]["UseTools"];
export type GroupChat = components["schemas"]["GroupChatPublic"];

// Flow types — manually defined until OpenAPI schema is generated
export type FlowStep = {
  id?: string | null;
  assistant_id: string;
  step_order: number;
  user_description?: string | null;
  input_source: "flow_input" | "previous_step" | "all_previous_steps" | "http_get" | "http_post";
  input_type: "text" | "json" | "image" | "audio" | "document" | "file" | "any";
  input_contract?: Record<string, unknown> | null;
  output_mode: "pass_through" | "http_post";
  output_type: "text" | "json" | "pdf" | "docx";
  output_contract?: Record<string, unknown> | null;
  input_bindings?: Record<string, unknown> | null;
  output_classification_override?: number | null;
  mcp_policy: "inherit" | "restricted";
  input_config?: Record<string, unknown> | null;
  output_config?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type FlowSparse = {
  id: string;
  tenant_id: string;
  space_id: string;
  name: string;
  description?: string | null;
  created_by_user_id?: string | null;
  owner_user_id?: string | null;
  published_version?: number | null;
  metadata_json?: Record<string, unknown> | null;
  data_retention_days?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type Flow = FlowSparse & {
  steps: FlowStep[];
};

export type FlowRunArtifact = {
  file_id: string;
  name: string;
  mimetype: string;
  size: number;
};

export type FlowRunOutputPayload = {
  text?: string;
  structured?: Record<string, unknown>;
  artifacts?: FlowRunArtifact[];
  generated_file_ids?: string[];
  file_ids?: string[];
  webhook_delivered?: boolean;
};

export type FlowRun = {
  id: string;
  flow_id: string;
  flow_version: number;
  user_id?: string | null;
  tenant_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  cancelled_at?: string | null;
  input_payload_json?: Record<string, unknown> | null;
  output_payload_json?: FlowRunOutputPayload | null;
  error_message?: string | null;
  job_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type FlowStepResult = {
  id?: string | null;
  flow_run_id: string;
  flow_id: string;
  tenant_id: string;
  step_id?: string | null;
  step_order: number;
  assistant_id?: string | null;
  input_payload_json?: Record<string, unknown> | null;
  effective_prompt?: string | null;
  output_payload_json?: FlowRunOutputPayload | null;
  model_parameters_json?: Record<string, unknown> | null;
  num_tokens_input?: number | null;
  num_tokens_output?: number | null;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  error_message?: string | null;
  tool_calls_metadata?: unknown[] | Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type FlowGraphNode = {
  id: string;
  label: string;
  type: "input" | "llm" | "output";
  step_order?: number;
  input_source?: string;
  input_type?: string;
  output_type?: string;
  output_mode?: string;
  mcp_policy?: string;
  run_status?: string;
  num_tokens_input?: number;
  num_tokens_output?: number;
  error_message?: string;
};

export type FlowGraphEdge = {
  source: string;
  target: string;
};

export type FlowGraph = {
  nodes: FlowGraphNode[];
  edges: FlowGraphEdge[];
};

export type FlowRunEvidence = {
  run: Record<string, unknown>;
  definition_snapshot: Record<string, unknown>;
  step_results: FlowStepResult[];
  step_attempts: Record<string, unknown>[];
};

export type DryRunResult = {
  step_order: number;
  step_id: string;
  valid: boolean;
  resolved_bindings?: Record<string, string>;
  errors?: string[];
};
export type GroupChatSparse = Omit<components["schemas"]["GroupChatSparse"], "user_id">;
export type ChatPartner =
  | { id: string; type: "assistant" }
  | { id: string; type: "group-chat" }
  | { id: string; type: "default-assistant" };

export type Paginated<T> = {
  items: T[];
  total_count: number;
  limit?: number | null;
  next_cursor?: string | null;
  previous_cursor?: string | null;
  count: number;
};

export namespace SSE {
  export type Text = Omit<components["schemas"]["SSEText"], "$defs">;
  export type FirstChunk = Omit<components["schemas"]["SSEFirstChunk"], "$defs">;
  export type Files = Omit<components["schemas"]["SSEFiles"], "$defs">;
  export type Intric = Omit<components["schemas"]["SSEIntricEvent"], "$defs">;
  export type ToolCall = Omit<components["schemas"]["SSEToolCall"], "$defs">;
  export type ToolApprovalRequired = {
    session_id: string;
    intric_event_type: "tool_approval_required";
    approval_id: string;
    tools: Array<{
      server_name: string;
      tool_name: string;
      arguments?: Record<string, unknown>;
      tool_call_id?: string;
    }>;
  };
  export type Error = Omit<components["schemas"]["SSEError"], "$defs">;
  export type Event = Text | FirstChunk | Files | Intric | ToolCall | ToolApprovalRequired | Error;
}

export type UserTokenUsageSummary = components["schemas"]["UserTokenUsageSummary"];
export type UserTokenUsage = components["schemas"]["UserTokenUsage"];
export type UserSortBy = components["schemas"]["UserSortBy"];
export type ModelUsage = components["schemas"]["ModelUsage"];
export type ModelKwargs = components["schemas"]["ModelKwargs"];

// Tenant model update types
export type TenantCompletionModelUpdate = components["schemas"]["TenantCompletionModelUpdate"];
export type TenantEmbeddingModelUpdate = components["schemas"]["TenantEmbeddingModelUpdate"];
export type TenantTranscriptionModelUpdate =
  components["schemas"]["TenantTranscriptionModelUpdate"];

// Federation types
export type TenantInfo = {
  slug: string;
  name: string;
  display_name: string;
};

export type TenantListResponse = {
  tenants: TenantInfo[];
};

export type InitiateAuthResponse = {
  authorization_url: string;
  state: string;
};

export type AccessTokenResponse = {
  access_token: string;
  token_type: string;
  expires_in?: number;
};
