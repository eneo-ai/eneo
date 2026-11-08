"""Canonical migration targets for legacy page URLs."""

import re

_LEGACY_PAGES = (
    (r"/news", "/whats-new"),
    (r"/admin/legacy/user-groups", "/admin/user-groups"),
    (r"/admin/personal-assistant/configuration", "/admin/personal-assistant"),
    (r"/admin/personal-assistant/prompts(?:/[^/]+)?", "/admin/prompt-library"),
    (r"/admin/prompt-library/[^/]+", "/admin/prompt-library"),
    (
        r"/admin/templates/(?:edit/(?:app|assistant)/[^/]+|new/(?:app|assistant))",
        "/admin/templates",
    ),
    (r"/assistants", "/"),
)


def legacy_page_target(path: str) -> str | None:
    for pattern, target in _LEGACY_PAGES:
        if re.fullmatch(pattern, path.removesuffix("/")):
            return target
    return None
