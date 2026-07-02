from typing import List, Optional

from pydantic import BaseModel

from eneo.info_blobs.info_blob import (
    InfoBlobAddPublic,
    InfoBlobChunkInDBWithScore,
    InfoBlobMetadataFilter,
    InfoBlobPublic,
    Query,
)


class VersionResponse(BaseModel):
    version: str


class UpsertResponse(BaseModel):
    ids: List[str]


class ModelRequest(BaseModel):
    query: str


class ModelResponse(BaseModel):
    response: str


class InfoBlobUpsertRequest(BaseModel):
    info_blobs: list[InfoBlobAddPublic]


class InfoBlobUpsertResponse(BaseModel):
    info_blobs: list[InfoBlobPublic]


class GetInfoBlobsRequest(BaseModel):
    ids: Optional[list[str]]
    filter: Optional[InfoBlobMetadataFilter]


class GetInfoBlobsResponse(BaseModel):
    info_blobs: list[InfoBlobPublic]


class GetInfoBlobsMetadataRequest(BaseModel):
    filter: Optional[InfoBlobMetadataFilter] = None


class GetInfoBlobsMetadataResponse(BaseModel):
    info_blobs: list[InfoBlobPublic]


class InfoBlobDeleteRequest(BaseModel):
    ids: list[str]


class InfoBlobDeleteResponse(BaseModel):
    info_blob_deleted: InfoBlobPublic


class InfoBlobQueryRequest(BaseModel):
    query: Query


class InfoBlobQueryResponse(BaseModel):
    results: list[InfoBlobChunkInDBWithScore]
