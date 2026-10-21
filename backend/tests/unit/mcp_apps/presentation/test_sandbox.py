import json
import re

from eneo.mcp_apps.presentation.sandbox import sandbox_document


def _embedded_origins(document: str) -> list[str]:
    match = re.search(r"const hostOrigins = (\[.*?\]);", document)
    assert match is not None
    return json.loads(match.group(1))


def test_sandbox_document_carries_every_host_origin() -> None:
    document = sandbox_document(
        ["https://eneo.example.org", "https://next.example.org"]
    )

    assert _embedded_origins(document) == [
        "https://eneo.example.org",
        "https://next.example.org",
    ]
    assert "__HOST_ORIGINS__" not in document


def test_sandbox_document_cannot_be_closed_by_an_origin_value() -> None:
    document = sandbox_document(["https://x</script><script>alert(1)"])

    assert (
        "</script><script>"
        not in document.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    )
    assert _embedded_origins(document) == ["https://x</script><script>alert(1)"]


def test_sandbox_document_without_hosts_frames_nothing() -> None:
    assert _embedded_origins(sandbox_document([])) == []
