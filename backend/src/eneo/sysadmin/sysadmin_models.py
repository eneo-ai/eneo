from pydantic import BaseModel, Field

from eneo.main.models import ModelId
from eneo.spaces.api.space_models import AddSpaceMemberRequest


def _empty_model_id_list() -> list[ModelId]:
    return []


def _empty_member_list() -> list[AddSpaceMemberRequest]:
    return []


class InfoBlobDifference(BaseModel):
    database_ids: set[str]
    datastore_ids: set[str]
    database_difference: set[str]
    datastore_difference: set[str]


class ExtraBlobs(BaseModel):
    count: int
    ids: list[str]


class AggregatedExtraBlobs(BaseModel):
    database: ExtraBlobs
    datastore: ExtraBlobs


class InfoBlobDifferencePublic(BaseModel):
    database_count: int
    datastore_count: int
    extra_info_blobs: AggregatedExtraBlobs


class CreateAndImportSpaceRequest(BaseModel):
    name: str
    embedding_model: ModelId
    assistants: list[ModelId] = Field(default_factory=_empty_model_id_list)
    groups: list[ModelId] = Field(default_factory=_empty_model_id_list)
    websites: list[ModelId] = Field(default_factory=_empty_model_id_list)
    members: list[AddSpaceMemberRequest] = Field(default_factory=_empty_member_list)
