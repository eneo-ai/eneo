import re
import shlex
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
