import re
import shlex
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
APPLICATION_IMAGE_DOCKERFILES = (
    REPO_ROOT / ".devcontainer" / "Dockerfile",
    REPO_ROOT / "backend" / "Dockerfile",
)
NATIVE_RUNTIME_PACKAGES = (
    "ffmpeg",
    "fontconfig",
    "fonts-dejavu-core",
    "libharfbuzz-subset0",
    "libmagic1",
    "libpango-1.0-0",
    "libpangoft2-1.0-0",
    "libsndfile1",
)
RUNTIME_BOOTSTRAP_FILES = (
    REPO_ROOT / ".devcontainer" / "post-create.sh",
    REPO_ROOT / "docker-compose.e2e.yml",
    REPO_ROOT / "docker-compose.e2e.ci.yml",
)
DEPLOYMENT_COMPOSE = REPO_ROOT / "docs" / "deployment" / "docker-compose.yml"
DEPLOYMENT_ENV_TEMPLATE = REPO_ROOT / "docs" / "deployment" / ".env.template"
BACKEND_PROJECT = REPO_ROOT / "backend" / "pyproject.toml"
REQUIRED_IMAGE_DIGESTS = (
    "TRAEFIK_IMAGE_DIGEST",
    "ENEO_FRONTEND_IMAGE_DIGEST",
    "ENEO_BACKEND_IMAGE_DIGEST",
    "PGVECTOR_IMAGE_DIGEST",
    "REDIS_IMAGE_DIGEST",
)
BASE_STACK_SERVICE_IMAGES = {
    "traefik": "traefik@sha256:${TRAEFIK_IMAGE_DIGEST:?Set TRAEFIK_IMAGE_DIGEST in .env}",
    "frontend": "ghcr.io/eneo-ai/eneo-frontend@sha256:${ENEO_FRONTEND_IMAGE_DIGEST:?Set ENEO_FRONTEND_IMAGE_DIGEST in .env}",
    "backend": "ghcr.io/eneo-ai/eneo-backend@sha256:${ENEO_BACKEND_IMAGE_DIGEST:?Set ENEO_BACKEND_IMAGE_DIGEST in .env}",
    "worker": "ghcr.io/eneo-ai/eneo-backend@sha256:${ENEO_BACKEND_IMAGE_DIGEST:?Set ENEO_BACKEND_IMAGE_DIGEST in .env}",
    "celery-worker-flows": "ghcr.io/eneo-ai/eneo-backend@sha256:${ENEO_BACKEND_IMAGE_DIGEST:?Set ENEO_BACKEND_IMAGE_DIGEST in .env}",
    "celery-worker-flows-maintenance": "ghcr.io/eneo-ai/eneo-backend@sha256:${ENEO_BACKEND_IMAGE_DIGEST:?Set ENEO_BACKEND_IMAGE_DIGEST in .env}",
    "celery-beat-flows": "ghcr.io/eneo-ai/eneo-backend@sha256:${ENEO_BACKEND_IMAGE_DIGEST:?Set ENEO_BACKEND_IMAGE_DIGEST in .env}",
    "db": "pgvector/pgvector@sha256:${PGVECTOR_IMAGE_DIGEST:?Set PGVECTOR_IMAGE_DIGEST in .env}",
    "redis": "redis@sha256:${REDIS_IMAGE_DIGEST:?Set REDIS_IMAGE_DIGEST in .env}",
    "db-init": "ghcr.io/eneo-ai/eneo-backend@sha256:${ENEO_BACKEND_IMAGE_DIGEST:?Set ENEO_BACKEND_IMAGE_DIGEST in .env}",
}
FLOW_CELERY_HEALTH_COMMANDS = {
    "celery-worker-flows": "flow-worker-health",
    "celery-worker-flows-maintenance": "flow-worker-health",
    "celery-beat-flows": "flow-beat-health",
}


def _apt_install_packages(dockerfile: Path) -> set[str]:
    source = dockerfile.read_text()
    install_blocks = re.findall(
        r"apt-get install\b(?P<packages>.*?)&&\s*rm", source, flags=re.DOTALL
    )
    assert install_blocks, f"{dockerfile} must contain an apt install layer"
    return {
        token
        for block in install_blocks
        for token in shlex.split(block.replace("\\\n", " "), comments=True)
        if not token.startswith("-")
    }


def _compose_service_images(source: str) -> dict[str, str]:
    service_images: dict[str, str] = {}
    current_service: str | None = None

    for line in source.splitlines():
        if service_match := re.fullmatch(r"  ([a-z0-9-]+):", line):
            current_service = service_match.group(1)
        elif current_service and (
            image_match := re.fullmatch(r"    image:\s+(.+)", line)
        ):
            service_images[current_service] = image_match.group(1)

    return service_images


def _compose_service_body(source: str, service: str) -> str:
    match = re.search(
        rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [a-z0-9-]+:|\Z)",
        source,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert match is not None, f"Missing deployment service: {service}"
    return match.group("body")


def test_application_images_install_native_runtime_dependencies() -> None:
    for dockerfile in APPLICATION_IMAGE_DOCKERFILES:
        installed_packages = _apt_install_packages(dockerfile)

        for package in NATIVE_RUNTIME_PACKAGES:
            assert package in installed_packages, (
                f"{dockerfile.relative_to(REPO_ROOT)} must install {package}"
            )


def test_runtime_dependencies_are_not_installed_after_image_build() -> None:
    for bootstrap_file in RUNTIME_BOOTSTRAP_FILES:
        assert "apt-get install" not in bootstrap_file.read_text()


def test_production_base_stack_images_require_immutable_digests() -> None:
    service_images = _compose_service_images(DEPLOYMENT_COMPOSE.read_text())

    assert service_images == BASE_STACK_SERVICE_IMAGES


def test_deployment_env_template_owns_base_stack_image_digest_inputs() -> None:
    digest_inputs = re.findall(
        r"^([A-Z0-9_]+_IMAGE_DIGEST)=$",
        DEPLOYMENT_ENV_TEMPLATE.read_text(),
        re.MULTILINE,
    )

    assert digest_inputs == list(REQUIRED_IMAGE_DIGESTS)


def test_flow_celery_roles_have_native_healthchecks() -> None:
    compose = DEPLOYMENT_COMPOSE.read_text()
    project_scripts = tomllib.loads(BACKEND_PROJECT.read_text())["project"]["scripts"]

    for service, command in FLOW_CELERY_HEALTH_COMMANDS.items():
        service_body = _compose_service_body(compose, service)
        assert f'test: ["CMD", "{command}"]' in service_body
        assert command in project_scripts
