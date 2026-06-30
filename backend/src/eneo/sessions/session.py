from enum import Enum
from typing import TYPE_CHECKING, Literal, Optional
from uuid import UUID

from pydantic import BaseModel

from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
from eneo.files.file_models import FilePublic
from eneo.info_blobs.info_blob import InfoBlobAskAssistantPublic
from eneo.main.models import DateTimeModelMixin, InDB
from eneo.questions.question import (
    McpToolReferencePublic,
    Message,
    Question,
    ToolCallInfo,
    UseTools,
    WebSearchResultPublic,
)

if TYPE_CHECKING:
    from eneo.assistants.api.assistant_models import AssistantSparse


class SessionFeedback(BaseModel):
    value: Literal[-1, 1]
    text: Optional[str] = None


class SessionBase(BaseModel):
    name: str


class SessionAdd(SessionBase):
    # Exactly one of user_id (real user) or api_key_id (service-key principal)
    # is set per session. The session_service write paths enforce this invariant.
    user_id: Optional[UUID] = None
    api_key_id: Optional[UUID] = None
    assistant_id: Optional[UUID] = None
    group_chat_id: Optional[UUID] = None


class SessionUpdate(SessionBase):
    id: UUID


class SessionInDB(SessionBase, InDB):
    user_id: Optional[UUID] = None
    api_key_id: Optional[UUID] = None
    feedback_value: Optional[Literal[-1, 1]] = None
    feedback_text: Optional[str] = None

    questions: list[Question] = []
    assistant: Optional["AssistantSparse"] = None
    group_chat_id: Optional[UUID] = None


class SessionUpdateRequest(SessionBase):
    id: UUID


class SessionMetadataPublic(SessionUpdateRequest, DateTimeModelMixin):
    pass


class SessionPublic(SessionMetadataPublic):
    messages: list[Message]
    feedback: Optional[SessionFeedback] = None


class SessionId(SessionUpdateRequest, DateTimeModelMixin):
    pass


class GroupChatInfo(BaseModel):
    """Information about the group chat related to this response"""

    id: UUID
    allow_mentions: bool
    show_response_label: bool


class AskChatResponse(BaseModel):
    session_id: UUID
    question: str
    answer: str
    files: list[FilePublic]
    generated_files: list[FilePublic]
    references: list[InfoBlobAskAssistantPublic]
    tools: UseTools
    web_search_references: list[WebSearchResultPublic]
    mcp_tool_references: list[McpToolReferencePublic] = []


class AskResponse(AskChatResponse):
    model: Optional[CompletionModelPublic] = None


class SessionResponse(BaseModel):
    sessions: list[SessionId]


# Server Sent Event Response Types


class EneoEventType(str, Enum):
    GENERATING_IMAGE = "generating_image"
    TOOL_CALL = "tool_call"
    TOOL_APPROVAL_REQUIRED = "tool_approval_required"
    TOOL_APPROVAL_TIMEOUT = "tool_approval_timeout"
    TOKEN_USAGE = "token_usage"


class SSEBase(BaseModel):
    session_id: UUID


class SSEText(SSEBase):
    answer: str
    references: list[InfoBlobAskAssistantPublic]


class SSEReasoning(SSEBase):
    """Event carrying a chunk of the model's reasoning/thinking text."""

    reasoning: str


class SSEFiles(SSEBase):
    generated_files: list[FilePublic]


class SSEEneoEvent(SSEBase):
    eneo_event_type: EneoEventType


class SSEToolCall(SSEBase):
    """Event emitted when MCP tools are being executed."""

    eneo_event_type: EneoEventType = EneoEventType.TOOL_CALL
    tools: list[ToolCallInfo]
    mcp_tool_references: list[McpToolReferencePublic] = []


class ToolCallResultPublic(BaseModel):
    """Lazy-loaded payload for a single tool call's upstream response.

    Keeping this out of the streaming hot path lets the SSE payload stay small
    even when a tool returns several KB of text.
    """

    tool_call_id: str
    result: Optional[str] = None
    mcp_tool_name: Optional[str] = None


class SSEToolApprovalRequired(SSEBase):
    """Event emitted when MCP tools require user approval before execution."""

    eneo_event_type: EneoEventType = EneoEventType.TOOL_APPROVAL_REQUIRED
    approval_id: str  # UUID to correlate approval response
    tools: list[ToolCallInfo]  # Tools pending approval


class SSEToolApprovalTimeout(SSEBase):
    """Event emitted when tool approval timed out."""

    eneo_event_type: EneoEventType = EneoEventType.TOOL_APPROVAL_TIMEOUT
    approval_id: str
    tools: list[ToolCallInfo]


class TokenUsageEvent(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    turn_tokens: int


class SSETokenUsage(SSEBase):
    eneo_event_type: EneoEventType = EneoEventType.TOKEN_USAGE
    usage: TokenUsageEvent


class SSEFirstChunk(AskChatResponse):
    pass


class SSEError(SSEBase):
    error: str
    error_code: Optional[int] = None


class ToolApprovalResponse(BaseModel):
    status: str
    approval_id: str
    decisions_received: int
    decisions_remaining: int
    unrecognized_tool_call_ids: list[str] = []


# Add the SSE models here in order to include them in the openapi schema
SSE_MODELS = [
    SSEText,
    SSEReasoning,
    SSEEneoEvent,
    SSEToolCall,
    SSEToolApprovalRequired,
    SSEToolApprovalTimeout,
    SSETokenUsage,
    SSEFiles,
    SSEFirstChunk,
    SSEError,
]

# Add standalone enums that need to be included in the openapi schema
SSE_ENUMS = [EneoEventType]
