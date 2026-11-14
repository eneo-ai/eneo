"""Sign-in reads its provider config only through sign_in_source.

FEDERATION_ENABLED selects the stored config or the OIDC_* settings, never
both. A module under authentication/ or users/ that read either directly
could mix them again, so this lists every such read and allows only the
selector's.
"""

import ast
from pathlib import Path

import eneo

SOURCES = Path(eneo.__file__).parent
SELECTED = {
    "federation_config",
    "oidc_discovery_endpoint",
    "oidc_client_id",
    "oidc_client_secret",
    "oidc_allowed_domains",
}
ALLOWED = {
    # The selector itself.
    ("authentication/oidc/sign_in_source.py", "federation_config"),
    ("authentication/oidc/sign_in_source.py", "oidc_discovery_endpoint"),
    ("authentication/oidc/sign_in_source.py", "oidc_client_id"),
    ("authentication/oidc/sign_in_source.py", "oidc_client_secret"),
    ("authentication/oidc/sign_in_source.py", "oidc_allowed_domains"),
    # API tokens in stored mode fall back to OIDC_ALLOWED_DOMAINS when the
    # stored config lists no domains.
    ("users/user_service.py", "oidc_allowed_domains"),
}


def _reads() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for package in ("authentication", "users"):
        for path in sorted((SOURCES / package).rglob("*.py")):
            relative = path.relative_to(SOURCES).as_posix()
            for node in ast.walk(ast.parse(path.read_text(), filename=relative)):
                if isinstance(node, ast.Attribute) and node.attr in SELECTED:
                    found.add((relative, node.attr))
    return found


def test_only_the_selector_reads_the_sign_in_config_or_the_oidc_settings():
    assert _reads() - ALLOWED == set()
