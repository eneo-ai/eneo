"""Production-image ABI and operational contracts; no services/network required."""

import importlib
import importlib.util
import json
import os
import ssl
import subprocess
import tempfile
import xml.parsers.expat
from pathlib import Path

import magic
from lxml import etree
from PIL import Image, features
from pillow_heif import register_heif_opener


def main() -> None:
    assert os.getuid() == 1000, "Preserve the deployed backend UID"
    for module in ("asyncpg", "psycopg2", "numpy", "cryptography", "greenlet"):
        importlib.import_module(module)
    assert ssl.create_default_context().cert_store_stats()["x509_ca"] > 0
    assert magic.from_buffer(b"plain text\n", mime=True) == "text/plain"
    assert (
        etree.fromstring(b"<document><text>hello</text></document>")[0].text == "hello"
    )
    assert etree.LIBXML_VERSION >= (2, 15, 4)
    assert xml.parsers.expat.version_info >= (2, 8, 5)
    assert importlib.util.find_spec("soundfile") is None
    assert importlib.util.find_spec("audioread") is None

    # lxml must load scanned system packages, not an older wheel-bundled copy.
    mappings = Path("/proc/self/maps").read_text()
    for name in ("libxml2", "libxslt"):
        paths = {line.split()[-1] for line in mappings.splitlines() if name in line}
        assert paths and all(path.startswith("/usr/lib/") for path in paths), paths
    assert "libsndfile" not in mappings
    print(
        json.dumps(
            {
                "libxml2": etree.LIBXML_VERSION,
                "libxslt": etree.LIBXSLT_VERSION,
                "expat": xml.parsers.expat.EXPAT_VERSION,
                "pillow_libtiff": features.version_codec("libtiff"),
                "openssl": ssl.OPENSSL_VERSION,
            }
        )
    )

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        register_heif_opener()
        source = Image.new("RGB", (8, 8), "red")
        for extension in ("png", "tiff", "heic"):
            path = root / f"image.{extension}"
            source.save(path)
            with Image.open(path) as result:
                result.load()
                assert result.size == (8, 8)
        # release_sbom.yml bootstraps its tool into a disposable venv.
        subprocess.run(
            ["python", "-m", "venv", str(root / "venv")], check=True, timeout=60
        )
        subprocess.run(
            [str(root / "venv/bin/python"), "-m", "pip", "--version"],
            check=True,
            timeout=10,
        )
        check_startup(root)


def check_startup(root: Path) -> None:
    """Check the actual packaged launcher without contacting DB/Redis."""
    commands = root / "commands"
    commands.mkdir()
    log = root / "startup.log"
    for command in ("arq", "alembic", "gunicorn"):
        stub = commands / command
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$STARTUP_LOG"\n')
        stub.chmod(0o755)
    environment = dict(
        os.environ, PATH=f"{commands}:{os.environ['PATH']}", STARTUP_LOG=str(log)
    )
    for role, expected in (
        ("general", "WorkerSettings"),
        ("crawler", "CrawlerWorkerSettings"),
    ):
        log.unlink(missing_ok=True)
        subprocess.run(
            ["bash", "/app/run.sh"],
            check=True,
            timeout=10,
            env=dict(environment, RUN_AS_WORKER="TRUE", WORKER_ROLE=role),
        )
        assert log.read_text().strip().endswith(f"arq src.eneo.worker.arq.{expected}")
    result = subprocess.run(
        ["bash", "/app/run.sh"],
        timeout=10,
        env=dict(environment, RUN_AS_WORKER="true", WORKER_ROLE="invalid"),
    )
    assert result.returncode == 2
    for openapi in ("true", "false"):
        log.unlink(missing_ok=True)
        subprocess.run(
            ["bash", "/app/run.sh"],
            check=True,
            timeout=10,
            env=dict(
                environment,
                RUN_AS_WORKER="false",
                OPENAPI_ONLY_MODE=openapi,
                NUM_WORKERS="1",
            ),
        )
        recorded = log.read_text()
        assert ("alembic upgrade head" in recorded) == (openapi == "false")
        assert "gunicorn src.eneo.server.main:app --workers 1" in recorded
        assert "--keep-alive 75 --bind 0.0.0.0:8000" in recorded


if __name__ == "__main__":
    main()
