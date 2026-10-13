"""The one definition of what is unsafe inside an HTTP header value.

Shared by every place that puts caller-derived text on an outbound request, so
a single reviewed rule decides it. What each caller does with an unsafe value
is its own policy: MCP identity headers strip it, configurable provider
headers block the request.
"""


def is_unsafe_header_char(ch: str) -> bool:
    """True for CR, LF, NUL and every other non-printable character.

    That covers the C0/C1 control ranges and Unicode separators and format
    characters. The plain space is allowed.
    """
    return ch != " " and not ch.isprintable()
