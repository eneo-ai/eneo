"""Inspect effective routes, including inherited dependencies and mounted APIs.

FastAPI's route-context iterator owns lazy include resolution. Using its actual
dependency graph avoids reconstructing authorization from source-text matches.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIWebSocketRoute, RouteContext, iter_route_contexts
from starlette.routing import BaseRoute, Mount, Route

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    access_for,
    endpoint_access,
    has_authentication,
)


@dataclass(frozen=True)
class EndpointRoute:
    path: str
    endpoint: object
    dependant: Dependant | None
    context: RouteContext


def endpoint_routes(
    routes: Sequence[BaseRoute], *, prefix: str = ""
) -> Iterator[EndpointRoute]:
    for context in iter_route_contexts(routes):
        # Included WebSocket/Starlette routes carry their effective path and
        # dependencies on the materialized route rather than the HTTP context.
        materialized = getattr(context, "starlette_route", None)
        if isinstance(materialized, BaseRoute):
            context = RouteContext(materialized)
        path = prefix + (context.path or "")
        original = context.original_route
        if isinstance(original, Mount):
            if original.routes:
                yield from endpoint_routes(original.routes, prefix=path)
            else:
                # Protocol applications such as FastMCP own their own request
                # dispatch. The exact mount must declare transport admission.
                yield EndpointRoute(path, original.app, None, context)
            continue
        dependant = getattr(context, "dependant", None)
        if not isinstance(dependant, Dependant):
            dependant = (
                original.dependant if isinstance(original, APIWebSocketRoute) else None
            )
        if context.endpoint is None:
            raise ValueError(
                f"Cannot inspect endpoint access for {path}: {type(original)}"
            )
        yield EndpointRoute(path, context.endpoint, dependant, context)


def access_violations(route: EndpointRoute) -> list[str]:
    policy = access_for(route.endpoint)
    if policy is None:
        return [f"{route.path}: missing explicit authentication and authorization"]
    if has_authentication(policy, route.dependant):
        return []
    if route.dependant is None:
        return [f"{route.path}: protected endpoint has no authentication dependency"]
    return [
        f"{route.path}: declares {policy.authentication.value}, "
        "but its dependency graph does not authenticate that identity"
    ]


def validate_endpoint_access(app: FastAPI) -> None:
    violations = [
        violation
        for route in endpoint_routes(app.routes)
        for violation in access_violations(route)
    ]
    if violations:
        raise ValueError("Invalid endpoint access contracts:\n" + "\n".join(violations))


def declare_framework_documentation_access(app: FastAPI) -> None:
    """Explicit grants for the exact documentation routes FastAPI generated."""
    documentation_paths = {
        app.openapi_url,
        app.docs_url,
        app.redoc_url,
        app.swagger_ui_oauth2_redirect_url,
    } - {None}
    for route in app.routes:
        if isinstance(route, Route) and route.path in documentation_paths:
            endpoint_access(
                authentication=Authentication.PUBLIC,
                authorization=Authorization.PUBLIC,
                reason="Published API schemas and interactive API documentation.",
            )(route.endpoint)
