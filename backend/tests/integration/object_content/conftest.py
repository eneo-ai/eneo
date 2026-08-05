import functools
import json
import os
import shutil
import socket
from collections.abc import AsyncGenerator, Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from uuid import UUID, uuid4

import psycopg2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from sqlalchemy import text
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from eneo.database.database import DatabaseSessionManager
from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.s3_object_store import S3ObjectStore
from init_db import add_tenant_user

_WORKSPACE = Path("/workspace")


@functools.cache
def _workspace_host_source() -> str | None:
    """Host-side path of the /workspace mount, when running in the devcontainer.

    The devcontainer talks to the HOST docker daemon, so bind-mount sources
    must be host paths: a path under the container's own /tmp does not exist
    for the daemon and mounts as an empty directory. The host location of
    /workspace is read from this container's own mount table.
    """
    if not _WORKSPACE.is_dir():
        return None
    try:
        import docker

        client = docker.from_env()
        try:
            me = client.containers.get(socket.gethostname())
            for mount in me.attrs.get("Mounts", []):
                if mount.get("Destination") == str(_WORKSPACE):
                    return mount.get("Source")
        finally:
            client.close()
    except Exception:
        return None
    return None


@contextmanager
def _container_bound_directory(
    prefix: str,
) -> Iterator[tuple[Path, Callable[[Path], str]]]:
    """Directory for files that get bind-mounted into test containers.

    Yields (directory, bind_source): write files into `directory`, pass
    `bind_source(file)` as the volume-mapping source. Outside the devcontainer
    this is a plain TemporaryDirectory with identity translation; inside the
    devcontainer the directory lives under the /workspace mount and
    bind_source rewrites each path to its host-side equivalent so the host
    daemon can see it.
    """
    host_source = _workspace_host_source()
    if host_source is None:
        with TemporaryDirectory(prefix=prefix) as directory:
            yield Path(directory), str
        return

    base = _WORKSPACE / "backend" / ".pytest-container-mounts"
    base.mkdir(exist_ok=True)
    directory = Path(mkdtemp(prefix=prefix, dir=base))
    # The store container drops to a non-root service UID that must traverse
    # into the directory to read the mounted files.
    os.chmod(directory, 0o755)
    try:
        yield (
            directory,
            lambda p: str(Path(host_source) / Path(p).relative_to(_WORKSPACE)),
        )
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        try:
            base.rmdir()
        except OSError:
            pass


def pytest_collection_modifyitems(config, items):
    """Pin this directory's tests to one xdist worker.

    The fixtures here boot a second Postgres (pg13) and a SeaweedFS S3
    container per worker that touches them. Under ``--dist loadgroup`` the
    shared group keeps that to a single stack per run.
    """
    conftest_root = Path(__file__).parent.resolve()
    group_marker = pytest.mark.xdist_group("object_content")
    for item in items:
        if Path(item.path).resolve().is_relative_to(conftest_root):
            item.add_marker(group_marker)


POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_SEAWEEDFS_439_IMAGE = (
    "chrislusf/seaweedfs@"
    "sha256:c7d6c721b30ae711db766bbbfd40192776e263d4e51e22f57baef7bef93c12c6"
)
_CONFORMANCE_IMAGE = os.environ.get(
    "ENEO_TEST_S3_IMAGE",
    _SEAWEEDFS_439_IMAGE,
)

# TemporaryDirectory keeps the source directory owner-only (0700), while Docker
# bind-mounts each selected file directly into the isolated test container. The
# upstream image drops from the runner's UID to its non-root service UID before
# reading these mounts, so the files themselves need a read bit for that UID.
# Every value is generated test material and every mount remains read-only.
_CONTAINER_BOUND_TEST_FILE_MODE = 0o444


def _extra_tls_hosts() -> list[str]:
    """Extra hosts the S3 client may dial for the TLS store's published port.

    On a plain runner testcontainers resolves localhost. In the devcontainer
    it resolves the gateway of the docker bridge network the store container
    lands on, so that gateway IP must appear in the server certificate SANs.
    """
    if _workspace_host_source() is None:
        return []
    try:
        import docker

        client = docker.from_env()
        try:
            ipam = client.networks.get("bridge").attrs.get("IPAM") or {}
        finally:
            client.close()
        return [
            gateway
            for config in ipam.get("Config") or []
            if (gateway := config.get("Gateway"))
        ]
    except Exception:
        return []


def _tls_subject_alternative_names() -> list[x509.GeneralName]:
    names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ip_address("127.0.0.1")),
    ]
    for host in _extra_tls_hosts():
        try:
            names.append(x509.IPAddress(ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))
    return names


def _write_test_tls_material(directory: Path) -> tuple[Path, Path, Path]:
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Eneo object-content test CA")]
    )
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(_tls_subject_alternative_names()),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_path = directory / "ca.pem"
    certificate_path = directory / "server.pem"
    key_path = directory / "server-key.pem"
    ca_path.write_bytes(ca_certificate.public_bytes(serialization.Encoding.PEM))
    certificate_path.write_bytes(
        server_certificate.public_bytes(serialization.Encoding.PEM)
    )
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(ca_path, _CONTAINER_BOUND_TEST_FILE_MODE)
    os.chmod(certificate_path, _CONTAINER_BOUND_TEST_FILE_MODE)
    os.chmod(key_path, _CONTAINER_BOUND_TEST_FILE_MODE)
    return ca_path, certificate_path, key_path


@dataclass(frozen=True, slots=True)
class RealObjectStore:
    settings: ObjectContentSettings
    store: S3ObjectStore
    container: DockerContainer

    def stop_process(self) -> None:
        self.container.get_wrapped_container().stop(timeout=10)

    def start_process(self) -> None:
        self.container.get_wrapped_container().start()


@pytest.fixture(scope="session")
def object_content_postgres_13() -> Generator[PostgresContainer, None, None]:
    postgres = PostgresContainer(
        image=POSTGRES_13_IMAGE,
        username="object_content_test",
        password="object_content_test_password",
        dbname="object_content_test",
    )
    with postgres:
        postgres.get_connection_url()
        yield postgres


@pytest.fixture(scope="session")
async def _object_content_database(
    object_content_postgres_13: PostgresContainer,
) -> AsyncGenerator[DatabaseSessionManager, None]:
    host = object_content_postgres_13.get_container_host_ip()
    port = int(object_content_postgres_13.get_exposed_port(5432))
    credentials = "object_content_test:object_content_test_password"
    database_name = "object_content_test"
    sync_url = f"postgresql+psycopg2://{credentials}@{host}:{port}/{database_name}"
    async_url = f"postgresql+asyncpg://{credentials}@{host}:{port}/{database_name}"

    backend_dir = Path(__file__).resolve().parents[3]
    alembic_config = Config(str(backend_dir / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_config.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(alembic_config, "head")

    connection = psycopg2.connect(
        host=host,
        port=port,
        dbname=database_name,
        user="object_content_test",
        password="object_content_test_password",
    )
    try:
        add_tenant_user(
            connection,
            tenant_name="object-content-test",
            quota_limit=1_000_000,
            user_name="object-content-test",
            user_email="object-content@example.test",
            user_password="object-content-test-password",
        )
    finally:
        connection.close()

    database = DatabaseSessionManager()
    database.init(async_url)
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def object_content_database(
    _object_content_database: DatabaseSessionManager,
) -> AsyncGenerator[DatabaseSessionManager, None]:
    """Reset only the object-content control plane between integration tests."""
    async with _object_content_database.session() as session, session.begin():
        await session.execute(
            text(
                "TRUNCATE TABLE "
                "object_store_connections, "
                "object_contents, "
                "object_content_orphan_candidates, "
                "object_content_multipart_candidates, "
                "object_content_reconciliation_state "
                "CASCADE"
            )
        )
        await session.execute(
            text("INSERT INTO object_content_reconciliation_state DEFAULT VALUES")
        )
    yield _object_content_database


@pytest.fixture(scope="session")
async def _real_object_store_process(
    unused_tcp_port_factory: Callable[[], int],
) -> AsyncGenerator[RealObjectStore, None]:
    bucket = "eneo-object-content-test"
    unpaired_bucket = "eneo-object-content-unpaired-test"
    access_key = "object-content-test-key"
    secret_key = "object-content-test-secret"
    identity = {
        "identities": [
            {
                "name": "object-content-tests",
                "credentials": [{"accessKey": access_key, "secretKey": secret_key}],
                "actions": [
                    f"Read:{bucket}",
                    f"Read:{bucket}/*",
                    f"Write:{bucket}",
                    f"Write:{bucket}/*",
                    f"List:{bucket}",
                    f"Read:{unpaired_bucket}",
                    f"Read:{unpaired_bucket}/*",
                    f"Write:{unpaired_bucket}",
                    f"Write:{unpaired_bucket}/*",
                    f"List:{unpaired_bucket}",
                ],
            }
        ]
    }
    with _container_bound_directory("eneo-object-content-store-") as (
        directory,
        bind_source,
    ):
        host_port = unused_tcp_port_factory()
        config_path = Path(directory) / "s3.json"
        config_path.write_text(json.dumps(identity), encoding="utf-8")
        os.chmod(config_path, _CONTAINER_BOUND_TEST_FILE_MODE)
        container = (
            DockerContainer(_CONFORMANCE_IMAGE)
            .with_bind_ports(8333, host_port)
            .with_volume_mapping(
                bind_source(config_path),
                "/etc/seaweedfs/s3.json",
                mode="ro",
            )
            .with_command(
                "mini -dir=/data "
                "-bucket=eneo-object-content-test,eneo-object-content-unpaired-test "
                "-s3.config=/etc/seaweedfs/s3.json -s3.iam=false "
                "-webdav=false -admin.ui=false -master.telemetry=false"
            )
            .waiting_for(
                LogMessageWaitStrategy(
                    "All enabled components are running"
                ).with_startup_timeout(90)
            )
        )
        with container:
            host = container.get_container_host_ip()
            port = int(container.get_exposed_port(8333))
            settings = ObjectContentSettings(
                _env_file=None,
                endpoint_url=f"http://{host}:{port}",
                region="local",
                bucket=bucket,
                access_key_id=access_key,
                secret_access_key=secret_key,
                deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
                allow_insecure_http=True,
                io_chunk_bytes=64 * 1024,
                spool_memory_bytes=1024 * 1024,
                multipart_part_bytes=5 * 1024 * 1024,
                multipart_threshold_bytes=5 * 1024 * 1024,
                pending_stale_seconds=1,
                orphan_grace_seconds=1,
            )
            store = S3ObjectStore(settings)
            await store.check_ready()
            try:
                yield RealObjectStore(
                    settings=settings,
                    store=store,
                    container=container,
                )
            finally:
                await store.close()


@pytest.fixture
async def real_object_store(
    _real_object_store_process: RealObjectStore,
) -> AsyncGenerator[RealObjectStore, None]:
    # Namespaces accumulate only inside this disposable session container;
    # session teardown destroys them with the shared SeaweedFS process.
    settings = _real_object_store_process.settings.model_copy(
        update={"deployment_id": uuid4()}
    )
    store = S3ObjectStore(settings)
    await store.check_ready()
    try:
        yield RealObjectStore(
            settings=settings,
            store=store,
            container=_real_object_store_process.container,
        )
    finally:
        await store.close()


@pytest.fixture
async def real_unpaired_object_store(
    real_object_store: RealObjectStore,
) -> AsyncGenerator[RealObjectStore, None]:
    settings = real_object_store.settings.model_copy(
        update={"bucket": "eneo-object-content-unpaired-test"}
    )
    store = S3ObjectStore(settings)
    await store.check_ready()
    try:
        yield RealObjectStore(
            settings=settings,
            store=store,
            container=real_object_store.container,
        )
    finally:
        await store.close()


@pytest.fixture(scope="session")
async def real_tls_object_store(
    unused_tcp_port_factory: Callable[[], int],
) -> AsyncGenerator[RealObjectStore, None]:
    bucket = "eneo-object-content-tls-test"
    access_key = "object-content-tls-test-key"
    secret_key = "object-content-tls-test-secret"
    identity = {
        "identities": [
            {
                "name": "object-content-tls-tests",
                "credentials": [{"accessKey": access_key, "secretKey": secret_key}],
                "actions": [
                    f"Read:{bucket}",
                    f"Read:{bucket}/*",
                    f"Write:{bucket}",
                    f"Write:{bucket}/*",
                    f"List:{bucket}",
                ],
            }
        ]
    }
    with _container_bound_directory("eneo-object-content-tls-store-") as (
        test_directory,
        bind_source,
    ):
        host_port = unused_tcp_port_factory()
        config_path = test_directory / "s3.json"
        config_path.write_text(json.dumps(identity), encoding="utf-8")
        os.chmod(config_path, _CONTAINER_BOUND_TEST_FILE_MODE)
        ca_path, certificate_path, key_path = _write_test_tls_material(test_directory)
        container = (
            DockerContainer(_CONFORMANCE_IMAGE)
            .with_bind_ports(8443, host_port)
            .with_volume_mapping(
                bind_source(config_path),
                "/etc/seaweedfs/s3.json",
                mode="ro",
            )
            .with_volume_mapping(
                bind_source(ca_path),
                "/etc/seaweedfs/ca.pem",
                mode="ro",
            )
            .with_volume_mapping(
                bind_source(certificate_path),
                "/etc/seaweedfs/server.pem",
                mode="ro",
            )
            .with_volume_mapping(
                bind_source(key_path),
                "/etc/seaweedfs/server-key.pem",
                mode="ro",
            )
            .with_command(
                f"mini -dir=/data -bucket={bucket} "
                "-s3.config=/etc/seaweedfs/s3.json -s3.iam=false "
                "-s3.port=0 -s3.port.https=8443 "
                "-s3.cacert.file=/etc/seaweedfs/ca.pem "
                "-s3.cert.file=/etc/seaweedfs/server.pem "
                "-s3.key.file=/etc/seaweedfs/server-key.pem "
                "-webdav=false -admin.ui=false -master.telemetry=false"
            )
            .waiting_for(
                LogMessageWaitStrategy(
                    "All enabled components are running"
                ).with_startup_timeout(90)
            )
        )
        with container:
            host = container.get_container_host_ip()
            port = int(container.get_exposed_port(8443))
            settings = ObjectContentSettings(
                _env_file=None,
                endpoint_url=f"https://{host}:{port}",
                region="local",
                bucket=bucket,
                access_key_id=access_key,
                secret_access_key=secret_key,
                deployment_id=UUID("d2d69d7f-9ef1-443a-91ce-2541d49d14b7"),
                ca_bundle=ca_path,
                io_chunk_bytes=64 * 1024,
                spool_memory_bytes=1024 * 1024,
                multipart_part_bytes=5 * 1024 * 1024,
                multipart_threshold_bytes=5 * 1024 * 1024,
            )
            store = S3ObjectStore(settings)
            await store.check_ready()
            try:
                yield RealObjectStore(
                    settings=settings,
                    store=store,
                    container=container,
                )
            finally:
                await store.close()
