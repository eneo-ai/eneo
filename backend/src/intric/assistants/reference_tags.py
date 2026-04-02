from __future__ import annotations

import re

INLINE_REFERENCE_PATTERN = re.compile(r'<inref id="([0-9a-f]{8})"/>')


def extract_inline_reference_ids(text: str) -> list[str]:
    return list(dict.fromkeys(INLINE_REFERENCE_PATTERN.findall(text)))
