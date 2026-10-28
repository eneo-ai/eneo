"""GET routes are side-effect free under cookie auth, or declare why not.

A same-origin navigation carries the browser session cookie, so a cross-site
page can make the user's browser send any GET. Two guards keep GETs safe:

- every cookie-capable GET is classified: it is listed in
  ``read_only_get_routes.txt`` after review, or its ``endpoint_access``
  declares ``effect_on_get``; a new GET fails here until someone decides;
- the integration tests' tripwire fails a GET that writes without declaring it.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from starlette.routing import BaseRoute

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    EndpointAccess,
    access_for,
    endpoint_access,
)
from eneo.server.endpoint_routes import endpoint_routes, validate_endpoint_access
from tests.integration import safe_method_tripwire

READ_ONLY_GET_ROUTES = Path(__file__).with_name("read_only_get_routes.txt")

_USER = {
    "authentication": Authentication.USER,
    "authorization": Authorization.AUTHENTICATED,
    "reason": "Test route",
}
_PUBLIC = {
    "authentication": Authentication.PUBLIC,
    "authorization": Authorization.PUBLIC,
    "reason": "Test route",
}


def undeclared_cookie_gets(routes: list[BaseRoute]) -> set[str]:
    """Cookie-capable GETs without a declared effect: these must be read-only."""
    result: set[str] = set()
    for route in endpoint_routes(routes):
        policy = access_for(route.endpoint)
        methods = safe_method_tripwire.SAFE_METHODS & (route.context.methods or set())
        if (
            policy is not None
            and policy.authentication in safe_method_tripwire.COOKIE_CAPABLE
            and policy.effect_on_get is None
        ):
            result.update(f"{method} {route.path}" for method in methods)
    return result


def reviewed_read_only_gets() -> set[str]:
    lines = READ_ONLY_GET_ROUTES.read_text().splitlines()
    return {line for line in lines if line and not line.startswith("#")}


def test_every_cookie_capable_get_is_classified() -> None:
    from eneo.server.main import app

    undeclared = undeclared_cookie_gets(app.routes)
    reviewed = reviewed_read_only_gets()
    assert not undeclared - reviewed, (
        "New cookie-capable GET routes. Confirm each changes no state and add it "
        f"to {READ_ONLY_GET_ROUTES.name}, or declare endpoint_access("
        f"effect_on_get=...) with why the change is safe: {sorted(undeclared - reviewed)}"
    )
    assert not reviewed - undeclared, (
        f"Remove from {READ_ONLY_GET_ROUTES.name}, the routes are gone or declare "
        f"an effect: {sorted(reviewed - undeclared)}"
    )


def test_a_new_get_is_unclassified_until_reviewed() -> None:
    app = FastAPI()

    @app.get("/new")
    @endpoint_access(**_USER)
    async def new() -> None:
        return None

    @app.get("/declared")
    @endpoint_access(**_USER, effect_on_get="Writes a test row.")
    async def declared() -> None:
        return None

    @app.get("/public")
    @endpoint_access(**_PUBLIC)
    async def public() -> None:
        return None

    assert undeclared_cookie_gets(app.routes) == {"GET /new"}


@pytest.mark.parametrize(
    ("statement", "write"),
    [
        ("INSERT INTO t VALUES (1)", True),
        ("  update t SET a = 1", True),
        ("DELETE FROM t", True),
        ("WITH gone AS (DELETE FROM t RETURNING id) SELECT * FROM gone", True),
        ("SELECT * FROM t FOR UPDATE", False),
        ("WITH x AS (SELECT 1) SELECT * FROM x", False),
    ],
)
def test_sql_writes_are_recognised(statement: str, write: bool) -> None:
    assert safe_method_tripwire.is_sql_write(statement) is write


def test_redis_writes_are_recognised() -> None:
    assert safe_method_tripwire.is_redis_write(b"setex")
    assert safe_method_tripwire.is_redis_write("EVALSHA")
    assert not safe_method_tripwire.is_redis_write("GET")


def test_the_tripwire_reports_only_undeclared_writing_cookie_gets() -> None:
    # One shared in-memory database for the threadpool the handlers run in.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE t (a INTEGER)"))
    app = FastAPI()

    def write() -> None:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO t VALUES (1)"))

    @app.get("/undeclared")
    @endpoint_access(**_USER)
    def undeclared() -> None:
        write()

    @app.get("/raises")
    @endpoint_access(**_USER)
    def raises() -> None:
        write()
        raise RuntimeError("after the write committed")

    @app.get("/declared")
    @endpoint_access(**_USER, effect_on_get="Writes a test row.")
    def declared() -> None:
        write()

    @app.get("/public")
    @endpoint_access(**_PUBLIC)
    def public() -> None:
        write()

    @app.get("/read")
    @endpoint_access(**_USER)
    def read() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT * FROM t"))

    @app.post("/undeclared")
    @endpoint_access(**_USER)
    def post() -> None:
        write()

    violations: list[str] = []
    app.add_middleware(safe_method_tripwire.SafeMethodTripwire, violations=violations)
    stop = safe_method_tripwire.install()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        for path in ("/declared", "/public", "/read"):
            client.get(path)
        client.post("/undeclared")
        assert violations == []
        client.get("/undeclared")
        client.get("/raises")
    finally:
        stop()
    assert [violation.split(" changed")[0] for violation in violations] == [
        "GET /undeclared",
        "GET /raises",
    ]


def test_a_declared_effect_needs_a_reason() -> None:
    with pytest.raises(ValueError, match="effect on GET"):
        EndpointAccess(
            Authentication.PUBLIC, Authorization.PUBLIC, "Test route", effect_on_get=" "
        )


def test_an_effect_on_get_cannot_be_declared_on_a_route_without_get() -> None:
    app = FastAPI()

    @app.post("/write")
    @endpoint_access(**_PUBLIC, effect_on_get="Not a GET.")
    async def write() -> None:
        return None

    with pytest.raises(ValueError, match="declares an effect on GET but serves no GET"):
        validate_endpoint_access(app)
