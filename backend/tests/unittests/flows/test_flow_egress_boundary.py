"""Flow code reaches the network only through ``eneo.flows.runtime.egress``.

The scan parses every module under ``eneo/flows`` and ``eneo/flow_packages``
(imports at any nesting level, under an alias, under ``TYPE_CHECKING``) and,
outside the egress package and two named exceptions, fails when a module

* imports a third-party package that is not on ALLOWED_THIRD_PARTY. The list is
  the review checkpoint: a network client (boto3, dnspython, aioftp, pysftp,
  fabric, aiohttp, requests, ...) or a new HTTP stack (httpx2) must be named
  there, with the reason, before flow code may use it;
* imports httpx for anything but its passive types and exceptions, or reaches
  into an httpx submodule (``httpx._client``);
* imports a stdlib network or process module (socket, ssl, subprocess, ftplib,
  smtplib, xmlrpc, urllib.request, http.client, ...) or names ``urllib`` or
  ``http`` without a submodule;
* uses ``os.system``/``os.popen``/``os.exec*``/``os.spawn*``;
* imports or calls a socket-level API by name (``getaddrinfo``,
  ``create_connection``, ``open_connection``, ``connect_tcp``, ...), on any
  object, including ``from asyncio import open_connection``.

This is a guard for known direct sinks, not a proof. It cannot see dynamic
imports (``importlib.import_module``, ``__import__``), names built at run time
(``getattr(module, name)``), aliases made any other way than ``import ... as`` or
``alias = module``, or a connection opened inside an allowed package: an SDK such
as litellm or redis connects on its own, and weasyprint's URL fetcher is denied by
the renderer, not here. Reviewing what a new allowlist entry can reach is part of
adding it.

Two modules connect to endpoints a flow author cannot choose and are named
below with their reason; the destination policy does not apply to them.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src" / "eneo"
SCANNED_ROOTS = ("flows", "flow_packages")
EGRESS_PACKAGE = "flows/runtime/egress"

NAMED_EXCEPTIONS = {
    "flows/runtime/remote_transcription.py": (
        "the external transcription service URL is a deployment setting "
        "(FLOW_TRANSCRIPTION_SERVICE_URL), not something a flow author supplies"
    ),
    "flows/runtime/live_transcription/relay.py": (
        "the live transcription upstream is the api_base of a transcription "
        "model's provider, set by a tenant administrator "
        "(flow_live_transcription_socket_router._load_upstream_target), not by a "
        "flow author. It stays outside the destination policy for now because a "
        "local speech service is a legitimate target; a follow-up decides its policy"
    ),
}

# Third-party top-level packages flow code may import, with why they are not a
# way for a flow author to reach an arbitrary destination.
ALLOWED_THIRD_PARTY = {
    "anyio": "async helpers; its connect and DNS functions are refused by name below",
    "dependency_injector": "wiring",
    "docx": "Word documents, in memory",
    "docx2python": "Word documents, in memory",
    "fastapi": "the HTTP API flows serve",
    "httpx": "passive types and exceptions only, checked separately below",
    "jsonschema": (
        "validation; its own retrieval of a remote $ref is refused by the registry "
        "in eneo.flows.output_processing, the only module that may import it"
    ),
    "litellm": "model provider SDK; the destination is the tenant's provider setting",
    "lxml": "XML, in memory",
    "magic": "file type sniffing, in memory",
    "markdown_it": "markdown rendering",
    "opentelemetry": "telemetry to the operator's collector",
    "pydantic": "validation",
    "redis": "the operator's Redis; not a flow-author destination",
    "referencing": (
        "reference resolution for jsonschema. It has no network code: retrieval is a "
        "callback the registry in eneo.flows.output_processing supplies and that "
        "refuses every URI (test_schema_references); only that module may import it "
        "(test_flow_architecture_guards)"
    ),
    "sqlalchemy": "the operator's database",
    "sse_starlette": "server-sent events the API serves",
    "typing_extensions": "typing",
    "uuid_utils": "identifiers",
}
PASSIVE_HTTPX_NAMES = frozenset(
    {
        "Response",
        "Request",
        "Headers",
        "URL",
        "Timeout",
        "InvalidURL",
        "HTTPError",
        "TransportError",
        "TimeoutException",
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "WriteError",
        "WriteTimeout",
        "RemoteProtocolError",
        "ResponseNotRead",
    }
)
FORBIDDEN_STDLIB = frozenset(
    {
        "socket",
        "_socket",
        "ssl",
        "_ssl",
        "ctypes",
        "subprocess",
        "ftplib",
        "smtplib",
        "smtpd",
        "telnetlib",
        "imaplib",
        "poplib",
        "nntplib",
        "xmlrpc",
        "socketserver",
        "asyncore",
        "asynchat",
        "multiprocessing.connection",
        "urllib.request",
        "urllib.robotparser",
        "http.client",
        "http.server",
    }
)
# A namespace package whose network parts are submodules: naming it alone
# would let ``urllib.request`` be reached without an import this scan can see.
BARE_NAMESPACES = frozenset({"urllib", "http"})
SINK_NAMES = frozenset(
    {
        "getaddrinfo",
        "getnameinfo",
        "create_connection",
        "create_datagram_endpoint",
        "create_server",
        "create_unix_connection",
        "create_unix_server",
        "sock_connect",
        "open_connection",
        "open_unix_connection",
        "start_server",
        "start_unix_server",
        "create_subprocess_exec",
        "create_subprocess_shell",
        "subprocess_exec",
        "subprocess_shell",
        "connect_tcp",
        "connect_unix",
        "create_tcp_listener",
        "create_udp_socket",
    }
)
OS_PROCESS_NAMES = frozenset(
    {
        "system",
        "popen",
        "startfile",
        "posix_spawn",
        "posix_spawnp",
        *(
            f"exec{suffix}"
            for suffix in ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")
        ),
        *(
            f"spawn{suffix}"
            for suffix in ("l", "le", "lp", "lpe", "v", "ve", "vp", "vpe")
        ),
    }
)


@dataclass(frozen=True)
class Violation:
    line: int
    what: str


def _forbidden_stdlib(module: str) -> bool:
    return any(
        module == name or module.startswith(f"{name}.") for name in FORBIDDEN_STDLIB
    )


def scan_source(source: str) -> list[Violation]:
    tree = ast.parse(source)
    httpx_aliases: set[str] = set()
    os_aliases: set[str] = set()
    found: list[Violation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.extend(_check_module(node.lineno, alias.name, alias.name))
                top = alias.name.split(".")[0]
                if alias.name == "httpx":
                    httpx_aliases.add(alias.asname or "httpx")
                if alias.name == "os":
                    os_aliases.add(alias.asname or "os")
                if top in BARE_NAMESPACES and alias.name == top:
                    found.append(
                        Violation(node.lineno, f"import {top} without a submodule")
                    )
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                name = alias.name
                found.extend(
                    _check_module(node.lineno, node.module, f"{node.module}.{name}")
                )
                if name in SINK_NAMES:
                    found.append(
                        Violation(node.lineno, f"from {node.module} import {name}")
                    )
                if node.module == "os" and name in OS_PROCESS_NAMES:
                    found.append(Violation(node.lineno, f"from os import {name}"))
                if node.module == "httpx" and name not in PASSIVE_HTTPX_NAMES:
                    found.append(Violation(node.lineno, f"from httpx import {name}"))
    for node in ast.walk(tree):
        # ``client = httpx`` / ``system = os``: the alias reaches the same names.
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
            for aliases in (httpx_aliases, os_aliases):
                if node.value.id in aliases:
                    aliases.update(
                        target.id
                        for target in node.targets
                        if isinstance(target, ast.Name)
                    )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr in SINK_NAMES:
            found.append(Violation(node.lineno, f"socket-level call .{node.attr}"))
        if isinstance(node.value, ast.Name):
            if node.value.id in httpx_aliases and node.attr not in PASSIVE_HTTPX_NAMES:
                found.append(Violation(node.lineno, f"httpx.{node.attr}"))
            if node.value.id in os_aliases and node.attr in OS_PROCESS_NAMES:
                found.append(Violation(node.lineno, f"os.{node.attr}"))
    return sorted(found, key=lambda violation: violation.line)


def _check_module(line: int, module: str, described: str) -> list[Violation]:
    top = module.split(".")[0]
    if top == "eneo" or top == "__future__":
        return []
    if _forbidden_stdlib(module) or _forbidden_stdlib(described):
        return [Violation(line, f"import {described}")]
    if top in sys.stdlib_module_names:
        return []
    if top not in ALLOWED_THIRD_PARTY:
        return [Violation(line, f"third-party {top} is not on the allowlist")]
    if top == "httpx" and module != "httpx":
        return [Violation(line, f"httpx submodule {module}")]
    return []


def _flow_modules() -> list[Path]:
    return sorted(
        path
        for root in SCANNED_ROOTS
        for path in (SRC / root).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _relative(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def _scanned_modules() -> list[tuple[str, str]]:
    return [
        (_relative(path), path.read_text(encoding="utf-8"))
        for path in _flow_modules()
        if not _relative(path).startswith(f"{EGRESS_PACKAGE}/")
    ]


def test_no_flow_code_reaches_the_network_outside_the_egress_package():
    offenders: dict[str, list[str]] = {}
    for relative, source in _scanned_modules():
        if relative in NAMED_EXCEPTIONS:
            continue
        violations = scan_source(source)
        if violations:
            offenders[relative] = [f"{v.line}: {v.what}" for v in violations]
    assert not offenders, (
        "Flow code must reach the network through eneo.flows.runtime.egress, which "
        "applies the destination policy. Offending modules:\n"
        + "\n".join(f"  {name}: {hits}" for name, hits in offenders.items())
    )


@pytest.mark.parametrize("relative", sorted(NAMED_EXCEPTIONS))
def test_a_named_exception_still_exists_and_still_needs_it(relative: str):
    path = SRC / relative
    assert path.is_file(), f"{relative} is gone: remove its exception"
    assert scan_source(path.read_text(encoding="utf-8")), (
        f"{relative} no longer reaches the network directly: remove its exception"
    )
    assert NAMED_EXCEPTIONS[relative]


def test_every_allowlisted_package_is_still_used():
    used: set[str] = set()
    for _relative_path, source in _scanned_modules():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                used.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                used.add(node.module.split(".")[0])
    stale = sorted(set(ALLOWED_THIRD_PARTY) - used)
    assert not stale, (
        f"remove from ALLOWED_THIRD_PARTY, no flow module imports: {stale}"
    )


def test_the_egress_package_is_where_the_flow_http_client_is_built():
    egress_http = (SRC / EGRESS_PACKAGE / "http.py").read_text(encoding="utf-8")
    assert "httpx.AsyncClient" in egress_http
    sender = (SRC / "flows/runtime/http_runtime.py").read_text(encoding="utf-8")
    assert scan_source(sender) == []


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\nhttpx.AsyncClient()",
        "import httpx as h\nh.get('http://x')",
        "from httpx import AsyncClient",
        "import httpx._client",
        "from httpx._client import AsyncClient",
        "from httpx import _client",
        "import httpx2",
        "import socket",
        "import ssl",
        "def f():\n    import aiohttp",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import requests",
        "import boto3",
        "import botocore.client",
        "import dns.resolver",
        "import aioftp",
        "import pysftp",
        "from fabric import Connection",
        "import paramiko",
        "import asyncssh",
        "import websockets.asyncio.client",
        "import httpcore",
        "import subprocess",
        "from subprocess import run",
        "import xmlrpc.client",
        "import _socket",
        "import ctypes",
        "import multiprocessing.connection",
        "import httpx\nclient = httpx\nclient.AsyncClient()",
        "import os\nrunner = os\nrunner.system('curl x')",
        "import ftplib",
        "import smtplib",
        "from urllib import request",
        "import urllib.request",
        "import urllib\nurllib.request.urlopen('http://x')",
        "import http\nhttp.client.HTTPConnection('x')",
        "import http.client",
        "from http import client",
        "import os\nos.system('curl http://x')",
        "import os as o\no.popen('curl x')",
        "from os import system",
        "from os import execv",
        "import os\nos.execvp('curl', ['curl'])",
        "import asyncio\nasyncio.open_connection('h', 1)",
        "from asyncio import open_connection",
        "from asyncio import create_subprocess_exec",
        "async def f(loop):\n    await loop.getaddrinfo('h', 1)",
        "import anyio\nanyio.connect_tcp('h', 1)",
        "from anyio import connect_tcp",
    ],
)
def test_the_scanner_finds_each_known_sink(source: str):
    assert scan_source(source), source


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\ndef f(r: httpx.Response) -> httpx.Headers: ...",
        "import httpx\ntry:\n    pass\nexcept httpx.TimeoutException:\n    pass",
        "from httpx import Response, HTTPError",
        "from urllib.parse import urlsplit",
        "import urllib.parse",
        "from http import HTTPStatus",
        "import anyio\nanyio.sleep(1)",
        "import asyncio\nasyncio.sleep(1)",
        "import os\nos.environ.get('X')\nos.path.join('a', 'b')",
        "import pydantic\nfrom sqlalchemy.orm import Session",
        "from eneo.main.config import get_settings",
        "from __future__ import annotations",
    ],
)
def test_the_scanner_leaves_passive_use_alone(source: str):
    assert scan_source(source) == [], source
