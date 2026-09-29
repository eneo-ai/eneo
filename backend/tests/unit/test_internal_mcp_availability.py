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


def _enable_references(monkeypatch):
    monkeypatch.setattr(
        "eneo.files.file_reference.file_reference_base_url",
        lambda settings=None: "https://eneo.example",
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


def test_files_server_follows_the_per_file_original_flag_only(monkeypatch):
    # Storage is not a gate here: ``original_available`` already reflects
    # whether the deployment can serve the bytes (inline PostgreSQL content
    # always, object-store content only while a store is connected), so a
    # deployment without any object store attaches the server for its
    # PostgreSQL-backed originals and nothing else is consulted.
    _enable_references(monkeypatch)
    stored_file = _file()

    availability = resolve_internal_mcp_availability(
        assistant=_assistant(),
        completion_model=_model(),
        conversation_files=[stored_file, _file(stored=False)],
    )

    assert availability.files
    assert availability.referenced_file_ids == {stored_file.id}
    assert availability.url_only_file_ids == {stored_file.id}
