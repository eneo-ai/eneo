"""Real listeners for the egress tests: a server records how many connections it
accepted and every byte it received, so a test can prove that nothing reached
it. Optionally serves TLS and records the SNI the client sent."""

from __future__ import annotations

import asyncio
import datetime
import ssl
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import httpcore
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

OK_RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"


class RecordingServer:
    def __init__(self, response: bytes = OK_RESPONSE) -> None:
        self.response = response
        self.connections = 0
        self.received = bytearray()
        self.server_names: list[str | None] = []
        self.port = 0

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        try:
            data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2)
            self.received.extend(data)
            writer.write(self.response)
            await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass


@asynccontextmanager
async def recording_server(
    response: bytes = OK_RESPONSE, *, ssl_context: ssl.SSLContext | None = None
) -> AsyncIterator[RecordingServer]:
    recorder = RecordingServer(response)
    if ssl_context is not None:

        def _record_sni(
            _socket: ssl.SSLObject, server_name: str | None, _context: ssl.SSLContext
        ) -> None:
            recorder.server_names.append(server_name)

        ssl_context.sni_callback = _record_sni
    server = await asyncio.start_server(
        recorder._handle, "127.0.0.1", 0, ssl=ssl_context
    )
    recorder.port = server.sockets[0].getsockname()[1]
    try:
        yield recorder
    finally:
        server.close()
        await server.wait_closed()


def self_signed_certificate(directory: Path, host_name: str) -> Path:
    """Write a self-signed certificate and key for ``host_name``; return the
    PEM path (certificate and key in one file)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(host_name)]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = directory / f"{host_name}.pem"
    path.write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
        + key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path


def server_ssl_context(pem: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(pem))
    return context


def client_ssl_context(pem: Path) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(pem))


class SpyConnector(httpcore.AsyncNetworkBackend):
    """Stands in for the socket layer under the vetting: it records every
    address the vetted backend asks it to connect to and can forward that
    connection to a real local server, fail, or stall like a dead host."""

    def __init__(
        self,
        *,
        forward_to: int | None = None,
        fail_hosts: Sequence[str] = (),
        stall: bool = False,
    ) -> None:
        self.forward_to = forward_to
        self.fail_hosts = set(fail_hosts)
        self.stall = stall
        self.calls: list[tuple[str, int, float | None]] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.calls.append((host, port, timeout))
        if host in self.fail_hosts:
            raise httpcore.ConnectError("connection refused")
        if self.stall:
            try:
                with anyio.fail_after(timeout):
                    await anyio.sleep_forever()
            except TimeoutError as exc:
                raise httpcore.ConnectTimeout("connect timed out") from exc
        assert self.forward_to is not None
        return await httpcore.AnyIOBackend().connect_tcp(
            "127.0.0.1",
            self.forward_to,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def sleep(self, seconds: float) -> None:
        await anyio.sleep(seconds)


class FixedResolver:
    """A resolver that answers from a script: one answer per lookup, the last
    answer repeating, so a test can make a name change between lookups."""

    def __init__(self, *answers: Sequence[str]) -> None:
        self._answers = list(answers)
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> Sequence[str]:
        self.calls.append((host, port))
        index = min(len(self.calls), len(self._answers)) - 1
        return self._answers[index]


# What the one effective-URL reading refuses, at authoring and at runtime.
INVALID_URLS = [
    "",
    "   ",
    "example.com",
    "//example.com/",
    "http:example.com",
    "http:///path",
    "http://:80/",
    "file:///etc/passwd",
    "ftp://example.com/",
    "sftp://example.com/",
    "gopher://example.com/",
    "data:text/plain,hi",
    "ws://example.com/",
    "wss://example.com/",
    "javascript:alert(1)",
    "http://a.com:abc/",
    "http://a.com:99999/",
    "http://a.com:65536/",
    "http://a.com:0/",
    "http://a.com:-1/",
    "http://a.com:8080:9/",
    "http://[::1/",
    "http://[::1]x/",
    "http://[1:2:3:4:5:6:7:8:9]/",
    "http://[not-an-ip]/",
    "http://[fe80::1%25eth0]/",
    "http://[fe80::1%eth0]/",
    "http://user@example.com/",
    "http://user:pw@example.com/",
    "http://example.com\\@127.0.0.1/",
    "http://127.0.0.1:80@evil.example/",
    "http://a b.com/",
    "http://exa\tmple.com/",
    "http://example.com/\x00",
    "http://a..example/",
    "http://0177.0.0.1/",
    "http://256.1.1.1/",
    "https://xn--",
    "http://xn--a/",
    "http://xn--zzzz-.com/",
    "http://xn--127-0-0-1:35501/",
    "http://a_b!.example/",
    "http://" + "a" * 64 + ".example/",
    "http://" + ".".join(["a" * 60] * 5) + "/",
]
