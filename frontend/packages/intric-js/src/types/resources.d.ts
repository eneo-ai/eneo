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
export type Permission = components["schemas"]["Permission"];
export type Role = components["schemas"]["RolePublic"];
export type ResourcePermission = components["schemas"]["ResourcePermission"];
export type CrawlRun = components["schemas"]["CrawlRunPublic"];
export type Limits = components["schemas"]["Limits"];
export type UploadedFile = components["schemas"]["FilePublic"];
export type Website = components["schemas"]["WebsitePublic"];
export type Settings = components["schemas"]["SettingsPublic"];
export type FlowInputLimits = components["schemas"]["FlowInputLimitsPublic"];
export type FlowRuntimePolicy = components["schemas"]["FlowRuntimePolicyPublic"];
export type FlowRuntimePolicyUpdate = components["schemas"]["FlowRuntimePolicyUpdate"];
export type FlowEvidencePolicy = components["schemas"]["FlowEvidencePolicyPublic"];
export type FlowRetentionPolicy = components["schemas"]["FlowRetentionPolicyPublic"];
// SEAM: tracked in batch-5 journal; delete when schema.d.ts includes FlowDocumentRenderLimitsPublic.
export type FlowDocumentRenderLimits = {
  max_source_chars: number;
  max_blocks: number;
  max_text_chars: number;
  max_table_rows: number;
  max_table_columns: number;
  max_table_cells: number;
  max_cell_chars: number;
  max_list_items: number;
  max_structured_nodes: number;
  max_structured_depth: number;
  max_object_fields: number;
};
export type AIBuilderBudgetSettings = components["schemas"]["AIBuilderBudgetSettingsPublic"];
export type WebsiteSparse = components["schemas"]["WebsiteSparse"];
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

export type FlowStep = components["schemas"]["FlowStepPublic"];
export type FlowSparse = components["schemas"]["FlowSparsePublic"];
export type Flow = components["schemas"]["FlowPublic"];
export type FlowTemplatePlaceholder = components["schemas"]["FlowTemplatePlaceholderPublic"];
export type FlowTemplateInspection = components["schemas"]["FlowTemplateInspectionPublic"];
export type FlowTemplateAsset = components["schemas"]["FlowTemplateAssetPublic"];
export type FlowRunContractStepInput = components["schemas"]["FlowRuntimeInputContractPublic"];
export type FlowRunContractTemplateReadiness = components["schemas"]["FlowTemplateReadinessPublic"];
export type FlowRunContract = components["schemas"]["FlowRunContractPublic"];
export type AIBuilderAttachmentFile = components["schemas"]["FilePublic"];
export type AIBuilderConversationMessage = components["schemas"]["ConversationMessage"];
export type AIBuilderSessionResponse = components["schemas"]["SessionResponse"];
export type AIBuilderDraftSession = components["schemas"]["SessionListItemResponse"];
export type AIBuilderStepSpec = components["schemas"]["StepSpec"];
export type AIBuilderFlowDraftSpecCore = components["schemas"]["FlowDraftSpecCore"];
export type AIBuilderLintWarning = components["schemas"]["LintWarning"];
export type AIBuilderPlannerPlanEnvelope = components["schemas"]["PlannerPlanEnvelope"];
export type AIBuilderPlanResponse = components["schemas"]["PlanResponse"];
export type AIBuilderApplyResult = components["schemas"]["ApplyResultResponse"];
export type AIBuilderModel = components["schemas"]["SessionModelOption"];
export type AIBuilderSessionTelemetrySummary = components["schemas"]["SessionTelemetrySummary"];
export type FlowRunResultFile = components["schemas"]["FlowRunStepResultFile"];
export type FlowRunTokenUsage = components["schemas"]["FlowRunTokenUsagePublic"];

export type FlowRunOutputPayload = {
  text?: string;
  structured?: Record<string, unknown> | unknown[];
  webhook_delivered?: boolean;
  webhook_error?: string;
  template_fill_debug?: Record<string, unknown>;
  template_provenance?: Record<string, unknown>;
};

type WithTypedRunOutput<T extends { output_payload_json?: unknown }> = Omit<
  T,
  "output_payload_json"
> & {
  output_payload_json?: FlowRunOutputPayload | null;
};

export type FlowRun = WithTypedRunOutput<components["schemas"]["FlowRunPublic"]>;
export type FlowRunStepInput = components["schemas"]["StepRunInput"] & { file_ids: string[] };
export type FlowRunStepInputs = Record<string, FlowRunStepInput>;
export type FlowInputPolicy = components["schemas"]["FlowInputPolicyPublic"];
export type FlowRunStep = WithTypedRunOutput<components["schemas"]["FlowRunStepPublic"]>;
export type FlowGraphNode = components["schemas"]["GraphNode"];
export type FlowGraphEdge = components["schemas"]["GraphEdge"];
export type FlowGraph = components["schemas"]["GraphResponse"];
export type FlowRunDebugIoTypes = components["schemas"]["FlowRunDebugIoTypes"];
export type FlowRunDebugInput = components["schemas"]["FlowRunDebugInput"];
export type FlowRunDebugOutput = components["schemas"]["FlowRunDebugOutput"];
export type FlowRunDebugMcp = components["schemas"]["FlowRunDebugMcp"];
export type FlowRunDebugRagReferenceChunk = components["schemas"]["FlowRunDebugRagReferenceChunk"];
export type FlowRunDebugRagReference = components["schemas"]["FlowRunDebugRagReference"];
export type FlowRunDebugRag = components["schemas"]["FlowRunDebugRag"];
export type FlowRunDebugStep = components["schemas"]["FlowRunDebugStep"];
export type FlowRunDebugAttempt = components["schemas"]["FlowRunDebugAttempt"];
export type FlowRunDebugExport = components["schemas"]["FlowRunDebugExport"];
export type FlowRunRerunOperation = components["schemas"]["FlowRunRerunOperationPublic"];
export type FlowRunRerunInvalidatedStep =
  components["schemas"]["FlowRunRerunInvalidatedStepPublic"];
export type FlowRunReviewCheckpoint = components["schemas"]["FlowRunReviewCheckpointPublic"];
export type FlowRunReviewCheckpointState = components["schemas"]["FlowRunReviewCheckpointState"];
export type FlowRunReviewCheckpointResumeResponse =
  components["schemas"]["FlowRunReviewCheckpointResumeResponse"];
export type FlowRunEvidence = components["schemas"]["FlowRunEvidenceResponse"];
export type FlowRunEvidenceWithTypedSteps = Omit<FlowRunEvidence, "step_results"> & {
  step_results: FlowRunStep[];
};
export type FlowRunEvidenceExport = components["schemas"]["FlowRunEvidenceExportResponse"];
export type FlowRunRedispatchResult = components["schemas"]["FlowRunRedispatchResponse"];
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
