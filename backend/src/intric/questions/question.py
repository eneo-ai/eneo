from typing import Optional
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


# Models
class QuestionBase(BaseModel):
    question: str
    answer: str


class ToolCallInfo(BaseModel):
    """Info about a single tool being called."""

    server_name: str
    tool_name: str
    arguments: Optional[dict] = None
    tool_call_id: Optional[str] = None  # For tool approval flow
    approved: Optional[bool] = None  # True=approved, False=denied, None=auto-approved or pending


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

    @model_validator(mode="after")
    def require_one_of_session_id_and_service_id(self) -> "QuestionAdd":
        if self.service_id is None and self.session_id is None:
            raise ValueError("One of 'service_id' and 'session_id' is required")

        return self


class Question(QuestionAdd, InDB):
    logging_details: Optional[LoggingDetailsInDB] = None
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
    id: Optional[UUID] = None
    completion_model: Optional[CompletionModel] = None
    references: list[InfoBlobPublicNoText]
    files: list[FilePublic]
    tools: UseTools
    generated_files: list[FilePublic]
    web_search_references: list[WebSearchResultPublic]
    tool_calls: list[ToolCallInfo] = []

    @field_validator("tool_calls", mode="before")
    @classmethod
    def convert_none_to_empty_list(cls, v):
        return v if v is not None else []


class MessageLogging(Message):
    logging_details: LoggingDetailsPublic
