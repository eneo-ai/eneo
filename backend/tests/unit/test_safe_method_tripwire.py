"""The integration tests' GET tripwire and its endpoint_access declaration."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    EndpointAccess,
    endpoint_access,
)
from eneo.server.endpoint_routes import validate_endpoint_access
from tests.integration import safe_method_tripwire

_PUBLIC = {
    "authentication": Authentication.PUBLIC,
    "authorization": Authorization.PUBLIC,
    "reason": "Test route",
}


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


def test_only_undeclared_writing_gets_are_reported() -> None:
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
    @endpoint_access(**_PUBLIC)
    def undeclared() -> None:
        write()

    @app.get("/declared")
    @endpoint_access(**_PUBLIC, effect_on_get="Writes a test row.")
    def declared() -> None:
        write()

    @app.get("/read")
    @endpoint_access(**_PUBLIC)
    def read() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT * FROM t"))

    @app.post("/undeclared")
    @endpoint_access(**_PUBLIC)
    def post() -> None:
        write()

    violations: list[str] = []
    app.add_middleware(safe_method_tripwire.SafeMethodTripwire, violations=violations)
    stop = safe_method_tripwire.install()
    try:
        client = TestClient(app)
        for path in ("/declared", "/read"):
            client.get(path)
        client.post("/undeclared")
        assert violations == []
        client.get("/undeclared")
    finally:
        stop()
    assert len(violations) == 1
    assert violations[0].startswith("GET /undeclared changed state")


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
