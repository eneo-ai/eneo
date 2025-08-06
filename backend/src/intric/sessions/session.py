from enum import Enum
from typing import TYPE_CHECKING, Literal, Optional
from uuid import UUID

from pydantic import BaseModel

from intric.ai_models.completion_models.completion_model import CompletionModelPublic
from intric.files.file_models import FilePublic
from intric.info_blobs.info_blob import InfoBlobAskAssistantPublic
from intric.main.models import DateTimeModelMixin, InDB
from intric.questions.question import Message, Question, UseTools, WebSearchResultPublic

if TYPE_CHECKING:
    from intric.assistants.api.assistant_models import AssistantSparse


class SessionFeedback(BaseModel):
    value: Literal[-1, 1]
    text: Optional[str] = None


class SessionBase(BaseModel):
    name: str


class SessionAdd(SessionBase):
    user_id: UUID
    assistant_id: Optional[UUID] = None
    group_chat_id: Optional[UUID] = None


class SessionUpdate(SessionBase):
    id: UUID


class SessionInDB(SessionBase, InDB):
    user_id: UUID
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


class AskResponse(AskChatResponse):
    model: Optional[CompletionModelPublic] = None


class SessionResponse(BaseModel):
    sessions: list[SessionId]


# Server Sent Event Response Types


class IntricEventType(str, Enum):
    GENERATING_IMAGE = "generating_image"


class SSEBase(BaseModel):
    session_id: UUID


class SSEText(SSEBase):
    answer: str
    references: list[InfoBlobAskAssistantPublic]


class SSEFiles(SSEBase):
    generated_files: list[FilePublic]


class SSEIntricEvent(SSEBase):
    intric_event_type: IntricEventType


class SSEFirstChunk(AskChatResponse):
    pass


# Add the SSE models here in order to include them in the openapi schema
SSE_MODELS = [SSEText, SSEIntricEvent, SSEFiles, SSEFirstChunk]

# Add standalone enums that need to be included in the openapi schema
SSE_ENUMS = [IntricEventType]
