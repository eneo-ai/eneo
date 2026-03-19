from pydantic import BaseModel

from intric.main.models import ModelId
from intric.spaces.presentation.space_models import (  # type: ignore[import-not-found]
    AddSpaceMemberRequest,
)


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
    assistants: list[ModelId] = []
    groups: list[ModelId] = []
    websites: list[ModelId] = []
    members: list[AddSpaceMemberRequest] = []
