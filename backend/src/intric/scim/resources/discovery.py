from fastapi import APIRouter, Depends

from intric.scim.auth import require_scim_auth
from intric.scim.constants import (
    SCIM_BULK_MAX_OPERATIONS,
    SCIM_BULK_MAX_PAYLOAD_BYTES,
    SCIM_FILTER_MAX_RESULTS,
)
from intric.scim.openapi import scim_responses
from intric.scim.schemas.common import ListResponse

router = APIRouter(dependencies=[Depends(require_scim_auth)], tags=["SCIM Discovery"])


@router.get(
    "/ServiceProviderConfig",
    description="Get the SCIM service provider capabilities.",
    responses=scim_responses(401, 500),
    response_model=dict[str, object],
)
async def service_provider_config() -> dict[str, object]:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {
            "supported": True,
            "maxOperations": SCIM_BULK_MAX_OPERATIONS,
            "maxPayloadSize": SCIM_BULK_MAX_PAYLOAD_BYTES,
        },
        "filter": {"supported": True, "maxResults": SCIM_FILTER_MAX_RESULTS},
        "changePassword": {"supported": False},
        "sort": {"supported": True},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Authentication using a bearer token",
            }
        ],
    }


_USER_SCHEMA = {
    "id": "urn:ietf:params:scim:schemas:core:2.0:User",
    "name": "User",
    "description": "User account",
    "attributes": [
        {
            "name": "userName",
            "type": "string",
            "multiValued": False,
            "required": True,
            "caseExact": False,
            "mutability": "readWrite",
            "returned": "default",
            "uniqueness": "server",
        },
        {
            "name": "emails",
            "type": "complex",
            "multiValued": True,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
            "subAttributes": [
                {
                    "name": "value",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                },
                {
                    "name": "primary",
                    "type": "boolean",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                },
                {
                    "name": "type",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                },
            ],
        },
        {
            "name": "active",
            "type": "boolean",
            "multiValued": False,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
        },
        {
            "name": "externalId",
            "type": "string",
            "multiValued": False,
            "required": False,
            "caseExact": True,
            "mutability": "readWrite",
            "returned": "default",
            "uniqueness": "global",
        },
    ],
}

_GROUP_SCHEMA = {
    "id": "urn:ietf:params:scim:schemas:core:2.0:Group",
    "name": "Group",
    "description": "Group",
    "attributes": [
        {
            "name": "displayName",
            "type": "string",
            "multiValued": False,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
        },
        {
            "name": "members",
            "type": "complex",
            "multiValued": True,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
            "subAttributes": [
                {
                    "name": "value",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "immutable",
                    "returned": "default",
                },
                {
                    "name": "display",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "mutability": "immutable",
                    "returned": "default",
                },
            ],
        },
        {
            "name": "externalId",
            "type": "string",
            "multiValued": False,
            "required": False,
            "caseExact": True,
            "mutability": "readWrite",
            "returned": "default",
            "uniqueness": "none",
        },
    ],
}


@router.get(
    "/Schemas",
    description="List the SCIM schemas supported by this service.",
    responses=scim_responses(401, 500),
    response_model=ListResponse,
)
async def schemas() -> ListResponse:
    resources = [_USER_SCHEMA, _GROUP_SCHEMA]
    return ListResponse(
        totalResults=len(resources), itemsPerPage=len(resources), Resources=resources
    )


@router.get(
    "/ResourceTypes",
    description="List the SCIM resource types supported by this service.",
    responses=scim_responses(401, 500),
    response_model=ListResponse,
)
async def resource_types() -> ListResponse:
    resources = [
        {
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "schema": "urn:ietf:params:scim:schemas:core:2.0:User",
            "meta": {"resourceType": "ResourceType"},
        },
        {
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "schema": "urn:ietf:params:scim:schemas:core:2.0:Group",
            "meta": {"resourceType": "ResourceType"},
        },
    ]
    return ListResponse(
        totalResults=len(resources), itemsPerPage=len(resources), Resources=resources
    )
