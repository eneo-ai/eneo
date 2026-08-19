from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_ROOT.parent
FLOW_DOCS_ROOT = REPO_ROOT / "frontend" / "apps" / "docs-site" / "src" / "content"
FLOW_DOCS = (
    FLOW_DOCS_ROOT / "docs" / "flows.mdx",
    FLOW_DOCS_ROOT / "guides" / "flows-api-guide.mdx",
    FLOW_DOCS_ROOT / "guides" / "flows" / "index.mdx",
    FLOW_DOCS_ROOT / "guides" / "flows" / "designing-flows.mdx",
    FLOW_DOCS_ROOT / "guides" / "flows" / "integrating-flows.mdx",
    FLOW_DOCS_ROOT / "guides" / "flows" / "flows-faq.mdx",
    FLOW_DOCS_ROOT / "guides" / "flows" / "reference" / "errors.mdx",
    FLOW_DOCS_ROOT / "docs" / "flows-for-developers" / "index.mdx",
    FLOW_DOCS_ROOT / "docs" / "flows-for-developers" / "data-schema.mdx",
    FLOW_DOCS_ROOT / "docs" / "flows-for-developers" / "how-built.mdx",
    FLOW_DOCS_ROOT / "docs" / "flows-for-developers" / "key-decisions.mdx",
    FLOW_DOCS_ROOT / "docs" / "flows-for-developers" / "reviewing-flows-code.mdx",
    FLOW_DOCS_ROOT / "docs" / "flows-for-developers" / "run-lifecycle.mdx",
    FLOW_DOCS_ROOT / "docs" / "flows-for-developers" / "when-things-fail.mdx",
)


def test_flow_docs_are_hand_maintained_pages() -> None:
    for page in FLOW_DOCS:
        text = page.read_text()
        assert len(text.splitlines()) > 10, page
        assert "make docs:regen" not in text, page
        assert "backend/scripts/generate_flow_docs.py" not in text, page


def test_generated_flow_docs_toolchain_is_absent() -> None:
    removed_paths = (
        BACKEND_ROOT / "scripts" / "generate_flow_docs.py",
        BACKEND_ROOT / "scripts" / "flow_http_secret_inventory.py",
        BACKEND_ROOT
        / "src"
        / "eneo"
        / "flows"
        / "infrastructure"
        / "flow_schema_docs_exporter.py",
        BACKEND_ROOT
        / "src"
        / "eneo"
        / "flows"
        / "infrastructure"
        / "flow_secret_inventory.py",
    )
    assert not any(path.exists() for path in removed_paths)
