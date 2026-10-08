from fastapi import APIRouter, Depends

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.scim.auth import require_scim_auth
from eneo.scim.constants import (
    SCIM_BULK_MAX_OPERATIONS,
    SCIM_BULK_MAX_PAYLOAD_BYTES,
    SCIM_ENTERPRISE_USER_URN,
    SCIM_FILTER_MAX_RESULTS,
)
from eneo.scim.openapi import scim_responses
from eneo.scim.schemas.common import ListResponse

router = APIRouter(dependencies=[Depends(require_scim_auth)], tags=["SCIM Discovery"])


@router.get(
    "/ServiceProviderConfig",
    description="Get the SCIM service provider capabilities.",
    responses=scim_responses(401, 500),
    response_model=dict[str, object],
)
@endpoint_access(
    authentication=Authentication.SCIM,
    authorization=Authorization.SCIM,
    reason="The SCIM token authorizes provisioning only within its bound tenant.",
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


def _enterprise_string(name: str) -> dict[str, object]:
    return {
        "name": name,
        "type": "string",
        "multiValued": False,
        "required": False,
        "caseExact": False,
        "mutability": "readWrite",
        "returned": "default",
        "uniqueness": "none",
    }


# RFC 7643 §4.3 / §8.7.1. Advertised because it is persisted: discovery must
# stay truthful about what Eneo retains.
_ENTERPRISE_USER_SCHEMA = {
    "id": SCIM_ENTERPRISE_USER_URN,
    "name": "EnterpriseUser",
    "description": "Enterprise User",
    "attributes": [
        _enterprise_string("employeeNumber"),
        _enterprise_string("costCenter"),
        _enterprise_string("organization"),
        _enterprise_string("division"),
        _enterprise_string("department"),
        {
            "name": "manager",
            "type": "complex",
            "multiValued": False,
            "required": False,
            "mutability": "readWrite",
            "returned": "default",
            "subAttributes": [
                {
                    "name": "value",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "caseExact": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "none",
                },
                {
                    "name": "$ref",
                    "type": "reference",
                    "referenceTypes": ["User"],
                    "multiValued": False,
                    "required": False,
                    "caseExact": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "none",
                },
                {
                    "name": "displayName",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "caseExact": False,
                    "mutability": "readOnly",
                    "returned": "default",
                    "uniqueness": "none",
                },
            ],
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
@endpoint_access(
    authentication=Authentication.SCIM,
    authorization=Authorization.SCIM,
    reason="The SCIM token authorizes provisioning only within its bound tenant.",
)
async def schemas() -> ListResponse:
    resources = [_USER_SCHEMA, _ENTERPRISE_USER_SCHEMA, _GROUP_SCHEMA]
    return ListResponse(
        totalResults=len(resources), itemsPerPage=len(resources), Resources=resources
    )


@router.get(
    "/ResourceTypes",
    description="List the SCIM resource types supported by this service.",
    responses=scim_responses(401, 500),
    response_model=ListResponse,
)
@endpoint_access(
    authentication=Authentication.SCIM,
    authorization=Authorization.SCIM,
    reason="The SCIM token authorizes provisioning only within its bound tenant.",
)
async def resource_types() -> ListResponse:
    resources = [
        {
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "schema": "urn:ietf:params:scim:schemas:core:2.0:User",
            "schemaExtensions": [
                {"schema": SCIM_ENTERPRISE_USER_URN, "required": False}
            ],
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
