from typing import Any, Optional
from uuid import UUID

from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from intric.ai_models.completion_models.completion_model import CompletionModel
from intric.completion_models.infrastructure.web_search import WebSearchResult
from intric.files.file_models import File, FilePublic
from intric.info_blobs.info_blob import InfoBlobInDB, InfoBlobPublicNoText
from intric.logging.logging import (
    LoggingDetails,
    LoggingDetailsInDB,
    LoggingDetailsPublic,
)
from intric.main.models import InDB


# SubModels
class ToolAssistant(BaseModel):
    id: UUID
    handle: str = Field(
        validation_alias=AliasChoices("handle", "at-tag", "at_tag"),
        serialization_alias="handle",
    )


class Tools(BaseModel):
    assistants: list[ToolAssistant]


class UseTools(BaseModel):
    assistants: list[ToolAssistant]


class QuestionsFiles(BaseModel):
    type: str
    file: File

    model_config = ConfigDict(from_attributes=True)


class WebSearchResultPublic(BaseModel):
    id: UUID
    title: str
    url: str


class McpToolReferencePublic(InDB):
    """One MCP resource block captured from a tool call.

    Generic across MCP servers: only `uri`, `mime_type`, `content`, and the
    raw `meta` dict are exposed. Frontend may read generic keys from `meta`
    (e.g. `sourceType`, `title`) to drive richer affordances but must degrade
    gracefully when meta is empty.
    """

    uri: str
    mime_type: Optional[str] = None
    content: Optional[str] = None
    meta: dict[str, Any] = {}
    tool_call_id: Optional[str] = None
    mcp_tool_name: Optional[str] = None


# Models
class QuestionBase(BaseModel):
    question: str
    answer: str


class ToolCallInfo(BaseModel):
    """Info about a single tool being called."""

    server_name: str
    tool_name: str
    title: Optional[str] = None
    arguments: Optional[dict[str, object]] = None
    tool_call_id: Optional[str] = None  # For tool approval flow
    approved: Optional[bool] = (
        None  # True=approved, False=denied, None=auto-approved or pending
    )
    # Additive execution status for newer clients. Keep `approved` for compatibility.
    result_status: Optional[str] = None
    # Text extraction of the tool result. Required to replay tool use to the LLM
    # on later turns. Absent on rows persisted before this field was introduced;
    # such rows fall back to text-only replay (the model won't see the tool use).
    result: Optional[str] = None
    # The prefixed tool identifier the LLM sees when calling (e.g.
    # `server__tool`). Needed for replay so the tool_use name matches the
    # currently-registered tools. `tool_name` above is the unprefixed/display
    # form used by the UI.
    mcp_tool_name: Optional[str] = None


class QuestionAdd(QuestionBase):
    num_tokens_question: int
    num_tokens_answer: int
    tenant_id: UUID
    completion_model_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    service_id: Optional[UUID] = None
    logging_details: Optional[LoggingDetails] = None
    assistant_id: Optional[UUID] = None
    tool_calls: Optional[list[ToolCallInfo]] = None
    # Model reasoning/thinking text captured during streaming. Persisted so the
    # trace can be re-shown when a conversation is reloaded. None for turns
    # produced before this field existed or by models without reasoning.
    reasoning: Optional[str] = None

    @model_validator(mode="after")
    def require_one_of_session_id_and_service_id(self) -> "QuestionAdd":
        if self.service_id is None and self.session_id is None:
            raise ValueError("One of 'service_id' and 'session_id' is required")

        return self


class Question(QuestionAdd, InDB):
    logging_details: Optional[LoggingDetailsInDB] = None  # pyright: ignore[reportIncompatibleVariableOverride]  # Pydantic narrows type from LoggingDetails to LoggingDetailsInDB
    info_blobs: list[InfoBlobInDB] = []
    session_id: Optional[UUID] = None
    completion_model: Optional[CompletionModel] = None
    files: list[File] = []
    generated_files: list[File] = []
    assistant_name: Optional[str] = Field(
        validation_alias=AliasPath("assistant", "name"), default=None
    )
    questions_files: list[QuestionsFiles] = []
    web_search_results: list[WebSearchResult] = []
    mcp_tool_references: list[McpToolReferencePublic] = []
    tool_calls: Optional[list[ToolCallInfo]] = None

    @model_validator(mode="after")
    def process_files_from_db(self) -> "Question":
        """
        Process files from the database record.
        User files have type="user", assistant files have type="assistant"
        """
        if self.questions_files:
            self.files = [qf.file for qf in self.questions_files if qf.type == "user"]
            self.generated_files = [
                qf.file for qf in self.questions_files if qf.type == "assistant"
            ]

        return self


class Message(QuestionBase, InDB):
    id: Optional[UUID] = None  # pyright: ignore[reportIncompatibleVariableOverride]  # Pydantic allows None override of required UUID in InDB
    completion_model: Optional[CompletionModel] = None
    references: list[InfoBlobPublicNoText]
    files: list[FilePublic]
    tools: UseTools
    generated_files: list[FilePublic]
    web_search_references: list[WebSearchResultPublic]
    mcp_tool_references: list[McpToolReferencePublic] = []
    tool_calls: list[ToolCallInfo] = []
    reasoning: Optional[str] = None
    # Default 0 keeps deserialization safe for rows persisted before token
    # measurement was introduced. The DB columns are NOT NULL int, so every
    # persisted row reads back as an integer. Clients that sum these values
    # across history should treat 0 as "zero OR unmeasured" — historical
    # conversations from before measurement was added will underreport actual
    # context usage. Fix requires a backfill migration, out of scope here.
    num_tokens_question: int = 0
    num_tokens_answer: int = 0

    @field_validator("tool_calls", mode="before")
    @classmethod
    def convert_none_to_empty_list(
        cls, v: list[ToolCallInfo] | None
    ) -> list[ToolCallInfo]:
        return v if v is not None else []


class MessageLogging(Message):
    logging_details: LoggingDetailsPublic
