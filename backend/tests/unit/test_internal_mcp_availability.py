from types import SimpleNamespace
from uuid import uuid4

from eneo.assistants.api.assistant_models import KnowledgeMode
from eneo.files.file_models import FileType
from eneo.internal_mcp.availability import resolve_internal_mcp_availability


def _assistant(*, has_knowledge=True, mode=KnowledgeMode.TOOL, inline=False):
    return SimpleNamespace(
        knowledge_mode=mode,
        inline_file_text=inline,
        has_knowledge=lambda: has_knowledge,
    )


def _model(*, supports_tools=True):
    return SimpleNamespace(supports_tool_calling=supports_tools)


def _file(*, stored=True):
    return SimpleNamespace(
        id=uuid4(),
        file_type=FileType.TEXT,
        original_available=stored,
    )


def _enable_references(monkeypatch, *, object_store=True):
    monkeypatch.setattr(
        "eneo.files.file_reference.file_reference_base_url",
        lambda settings=None: "https://eneo.example",
    )
    monkeypatch.setattr(
        "eneo.files.file_reference.object_store_configured",
        lambda: object_store,
    )


def test_model_without_tool_calling_disables_all_internal_servers(monkeypatch):
    _enable_references(monkeypatch)

    availability = resolve_internal_mcp_availability(
        assistant=_assistant(),
        completion_model=_model(supports_tools=False),
        conversation_files=[_file()],
    )

    assert not availability.knowledge
    assert not availability.files
    assert not availability.url_only_file_ids
    assert not availability.referenced_file_ids


def test_runtime_gates_enable_knowledge_and_url_only_files(monkeypatch):
    _enable_references(monkeypatch)
    stored_file = _file()

    availability = resolve_internal_mcp_availability(
        assistant=_assistant(),
        completion_model=_model(),
        conversation_files=[stored_file, _file(stored=False)],
    )

    assert availability.knowledge
    assert availability.files
    assert availability.url_only_file_ids == {stored_file.id}
    assert availability.referenced_file_ids == {stored_file.id}


def test_files_server_follows_reference_urls_not_the_inlining_mode(monkeypatch):
    # The prompt renders reference entries (and names read_file) whenever URLs
    # can be minted, so the tool must attach even when the same files inline.
    _enable_references(monkeypatch)
    stored_file = _file()

    availability = resolve_internal_mcp_availability(
        assistant=_assistant(mode=KnowledgeMode.INJECT, inline=True),
        completion_model=_model(),
        conversation_files=[stored_file],
    )

    assert not availability.knowledge
    assert availability.files
    assert availability.referenced_file_ids == {stored_file.id}
    # Inlined files are not URL-only: their text still reaches the prompt.
    assert not availability.url_only_file_ids


def test_no_referenced_files_means_no_files_server(monkeypatch):
    _enable_references(monkeypatch)

    availability = resolve_internal_mcp_availability(
        assistant=_assistant(mode=KnowledgeMode.INJECT, inline=True),
        completion_model=_model(),
        conversation_files=[_file(stored=False)],
    )

    assert not availability.knowledge
    assert not availability.files
    assert not availability.referenced_file_ids


def test_files_server_requires_object_store(monkeypatch):
    _enable_references(monkeypatch, object_store=False)

    availability = resolve_internal_mcp_availability(
        assistant=_assistant(),
        completion_model=_model(),
        conversation_files=[_file()],
    )

    assert not availability.files
    assert not availability.referenced_file_ids
    assert not availability.url_only_file_ids
