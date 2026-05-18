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
// Backend's TenantPublic schema omits `id`, but the actual API response includes it.
// Until the schema is fixed upstream we extend the type so consumers can use `tenant.id`.
export type Tenant = components["schemas"]["TenantPublic"] & { id: string };
export type ModelProviderPublic = components["schemas"]["ModelProviderPublic"];
export type AnalyticsData = components["schemas"]["MetadataStatistics"];
export type AnalyticsAggregateRow = {
  created_at: string;
  count: number;
};
export type AnalyticsAggregatedData = {
  assistants: AnalyticsAggregateRow[];
  sessions: AnalyticsAggregateRow[];
  questions: AnalyticsAggregateRow[];
};
export type UserGroup = components["schemas"]["UserGroupPublic"];
export type User = components["schemas"]["UserAdminView"];
export type UserSparse = components["schemas"]["UserSparse"];
export type CurrentUser = components["schemas"]["UserPublic"];
export type Role = components["schemas"]["RolePublic"];
export type Permission = components["schemas"]["Permission"];
export type ResourcePermission = components["schemas"]["ResourcePermission"];
export type CrawlRun =
  components["schemas"]["intric__websites__presentation__website_models__CrawlRunPublic"];
export type CrawlOutcome = components["schemas"]["CrawlOutcomePublic"];
export type CrawlOutcomeCode = components["schemas"]["CrawlOutcomeCode"];
export type CrawlOutcomeSeverity = components["schemas"]["CrawlOutcomeSeverity"];
export type CrawlRunProcessingSummary = components["schemas"]["CrawlRunProcessingSummary"];
export type Limits = components["schemas"]["Limits"];
export type UploadedFile = components["schemas"]["FilePublic"];
export type Website = components["schemas"]["WebsitePublic"];
export type Settings = components["schemas"]["SettingsPublic"];
export type EffectiveCrawlerSettings = {
  crawl_max_length: number;
  download_timeout: number;
  download_max_size: number;
  dns_timeout: number;
  retry_times: number;
  closespider_itemcount: number;
  obey_robots: boolean;
  autothrottle_enabled: boolean;
  tenant_worker_concurrency_limit: number;
  crawl_stale_threshold_minutes: number;
  queued_stale_threshold_minutes: number;
  crawl_heartbeat_interval_seconds: number;
  crawl_feeder_enabled: boolean;
  crawl_feeder_interval_seconds: number;
  crawl_feeder_batch_size: number;
  crawl_job_max_age_seconds: number;
  tenant_worker_semaphore_ttl_seconds: number;
  crawl_page_batch_size: number;
  crawl_sitemap_lastmod_skip_enabled: boolean;
};
export type CrawlerSettings = {
  tenant_id: string;
  settings: EffectiveCrawlerSettings;
  overrides: string[];
  updated_at?: string | null;
  editable_settings?: string[];
  specs?: Partial<
    Record<
      keyof CrawlerSettingsUpdate,
      {
        type: "int" | "bool";
        description: string;
        min?: number | null;
        max?: number | null;
      }
    >
  >;
};
export type CrawlerSettingsUpdate = Partial<
  Pick<
    EffectiveCrawlerSettings,
    | "crawl_sitemap_lastmod_skip_enabled"
    | "obey_robots"
    | "autothrottle_enabled"
    | "download_max_size"
    | "download_timeout"
    | "dns_timeout"
    | "retry_times"
    | "closespider_itemcount"
  >
>;
export type CrawlerActiveInventoryResponse =
  components["schemas"]["CrawlerActiveInventoryResponse"];
export type CrawlerActiveInventoryItem = components["schemas"]["CrawlerActiveInventoryItem"];
export type CrawlerTenantFailureInventoryResponse =
  components["schemas"]["CrawlerTenantFailureInventoryResponse"];
export type CrawlerScheduledAggregateResponse =
  components["schemas"]["CrawlerScheduledAggregateResponse"];
export type CrawlerTenantWebsiteProcessingAggregateResponse =
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateResponse"];
export type CrawlerRecentFailuresResponse = components["schemas"]["CrawlerRecentFailuresResponse"];
export type CrawlerRecentFailureItem = components["schemas"]["CrawlerRecentFailureItem"];
export type CrawlerFailureClustersResponse =
  components["schemas"]["CrawlerFailureClustersResponse"];
export type CrawlerFailureClusterItem = components["schemas"]["CrawlerFailureClusterItem"];
export type CrawlerAbortConflictResponse = components["schemas"]["CrawlerAbortConflictResponse"];
// OpenAPI exposes website list/detail responses as WebsitePublic; the backend WebsiteSparse
// Pydantic model is not returned to frontend clients.
export type WebsiteSparse = components["schemas"]["WebsitePublic"];
export type Space = components["schemas"]["SpacePublic"];
export type SpaceSparse = components["schemas"]["SpaceSparse"];
export type Dashboard = components["schemas"]["Dashboard"];
export type Prompt = components["schemas"]["PromptPublic"];
export type PromptSparse = components["schemas"]["PromptSparse"];
export type IntricErrorCode = components["schemas"]["ErrorCodes"] | 0;
export type ApiKeyType = components["schemas"]["ApiKeyType"];
export type ApiKeyOwnership = components["schemas"]["ApiKeyOwnership"];
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
  export type ToolApprovalTimeout = {
    session_id: string;
    intric_event_type: "tool_approval_timeout";
    approval_id: string;
    tools: Array<{
      server_name: string;
      tool_name: string;
      arguments?: Record<string, unknown>;
      tool_call_id?: string;
      approved?: boolean;
      result_status?: string;
    }>;
  };
  export type TokenUsage = Omit<components["schemas"]["SSETokenUsage"], "$defs">;
  export type Error = Omit<components["schemas"]["SSEError"], "$defs">;
  export type Event =
    | Text
    | FirstChunk
    | Files
    | Intric
    | ToolCall
    | ToolApprovalRequired
    | ToolApprovalTimeout
    | TokenUsage
    | Error;
}

export type UserTokenUsageSummary = components["schemas"]["UserTokenUsageSummary"];
export type UserTokenUsage = components["schemas"]["UserTokenUsage"];
export type UserSortBy = components["schemas"]["UserSortBy"];
export type ModelUsage = components["schemas"]["ModelUsage"];
export type ModelKwargs = components["schemas"]["ModelKwargs"];
export type ModelKwargCapability = components["schemas"]["ModelKwargCapability"];
export type SupportedModelKwargs = components["schemas"]["SupportedModelKwargs"];

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
