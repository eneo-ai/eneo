from fastapi import APIRouter, Depends

from intric.scim.auth import require_scim_auth
from intric.scim.schemas.common import ListResponse

router = APIRouter(dependencies=[Depends(require_scim_auth)], tags=["SCIM Discovery"])


@router.get("/ServiceProviderConfig")
async def service_provider_config() -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": True, "maxOperations": 100, "maxPayloadSize": 1048576},
        "filter": {"supported": True, "maxResults": 200},
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
                {"name": "value", "type": "string", "multiValued": False, "required": False, "mutability": "readWrite", "returned": "default"},
                {"name": "primary", "type": "boolean", "multiValued": False, "required": False, "mutability": "readWrite", "returned": "default"},
                {"name": "type", "type": "string", "multiValued": False, "required": False, "mutability": "readWrite", "returned": "default"},
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
                {"name": "value", "type": "string", "multiValued": False, "required": False, "mutability": "immutable", "returned": "default"},
                {"name": "display", "type": "string", "multiValued": False, "required": False, "mutability": "immutable", "returned": "default"},
            ],
        },
    ],
}


@router.get("/Schemas")
async def schemas() -> ListResponse:
    resources = [_USER_SCHEMA, _GROUP_SCHEMA]
    return ListResponse(totalResults=len(resources), itemsPerPage=len(resources), Resources=resources)


@router.get("/ResourceTypes")
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
    return ListResponse(totalResults=len(resources), itemsPerPage=len(resources), Resources=resources)
