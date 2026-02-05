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
export type ApiKeyType = "pk_" | "sk_";
export type ApiKeyPermission = "read" | "write" | "admin";
export type ApiKeyScopeType = "tenant" | "space" | "assistant" | "app";
export type ApiKeyState = "active" | "suspended" | "revoked" | "expired";
export type ApiKeyStateReasonCode =
  | "security_concern"
  | "abuse_detected"
  | "user_request"
  | "admin_action"
  | "policy_violation"
  | "key_compromised"
  | "user_offboarding"
  | "rotation_completed"
  | "scope_removed"
  | "other";

export type ApiKeyV2 = {
  id: string;
  key_prefix: string;
  key_suffix: string;
  name: string;
  description?: string | null;
  key_type: ApiKeyType;
  permission: ApiKeyPermission;
  scope_type: ApiKeyScopeType;
  scope_id?: string | null;
  allowed_origins?: string[] | null;
  allowed_ips?: string[] | null;
  state: ApiKeyState;
  expires_at?: string | null;
  last_used_at?: string | null;
  revoked_at?: string | null;
  revoked_reason_code?: ApiKeyStateReasonCode | null;
  revoked_reason_text?: string | null;
  suspended_at?: string | null;
  suspended_reason_code?: ApiKeyStateReasonCode | null;
  suspended_reason_text?: string | null;
  rotation_grace_until?: string | null;
  rate_limit?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  rotated_from_key_id?: string | null;
};

export type ApiKeyCreateRequest = {
  name: string;
  description?: string | null;
  key_type: ApiKeyType;
  permission?: ApiKeyPermission;
  scope_type: ApiKeyScopeType;
  scope_id?: string | null;
  allowed_origins?: string[] | null;
  allowed_ips?: string[] | null;
  expires_at?: string | null;
  rate_limit?: number | null;
};

export type ApiKeyUpdateRequest = {
  name?: string | null;
  description?: string | null;
  allowed_origins?: string[] | null;
  allowed_ips?: string[] | null;
  expires_at?: string | null;
  rate_limit?: number | null;
};

export type ApiKeyStateChangeRequest = {
  reason_code?: ApiKeyStateReasonCode | null;
  reason_text?: string | null;
};

export type ApiKeyCreatedResponse = {
  api_key: ApiKeyV2;
  secret: string;
};

export type ApiKeyPolicy = {
  max_delegation_depth?: number | null;
  revocation_cascade_enabled?: boolean | null;
  require_expiration?: boolean | null;
  max_expiration_days?: number | null;
  auto_expire_unused_days?: number | null;
  max_rate_limit_override?: number | null;
};

export type SuperApiKeyStatus = {
  super_api_key_configured: boolean;
  super_duper_api_key_configured: boolean;
};

export type CursorPaginated<T> = {
  items: T[];
  total_count: number;
  limit?: number | null;
  next_cursor?: string | null;
  previous_cursor?: string | null;
};
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
  export type Event = Text | FirstChunk | Files | Intric;
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
