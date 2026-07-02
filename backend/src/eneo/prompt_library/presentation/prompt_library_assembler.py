# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from eneo.prompt_library.domain.prompt_library import (
    PromptLibraryEntry,
    PromptLibraryVersion,
)
from eneo.prompt_library.presentation.prompt_library_models import (
    PromptLibraryEntryPublic,
    PromptLibraryEntrySparse,
    PromptLibraryVersionPublic,
)


class PromptLibraryAssembler:
    @staticmethod
    def to_public(entry: PromptLibraryEntry) -> PromptLibraryEntryPublic:
        assert entry.id is not None
        assert entry.created_at is not None
        assert entry.updated_at is not None
        return PromptLibraryEntryPublic(
            id=entry.id,
            name=entry.name,
            description=entry.description,
            text=entry.text,
            current_version=entry.current_version,
            created_by_user_id=entry.created_by_user_id,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    @staticmethod
    def to_sparse(entry: PromptLibraryEntry) -> PromptLibraryEntrySparse:
        assert entry.id is not None
        assert entry.created_at is not None
        assert entry.updated_at is not None
        return PromptLibraryEntrySparse(
            id=entry.id,
            name=entry.name,
            description=entry.description,
            current_version=entry.current_version,
            created_by_user_id=entry.created_by_user_id,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    @staticmethod
    def version_to_public(version: PromptLibraryVersion) -> PromptLibraryVersionPublic:
        assert version.id is not None
        assert version.created_at is not None
        assert version.updated_at is not None
        return PromptLibraryVersionPublic(
            id=version.id,
            prompt_library_id=version.prompt_library_id,
            version=version.version,
            name=version.name,
            description=version.description,
            text=version.text,
            created_by_user_id=version.created_by_user_id,
            created_at=version.created_at,
            updated_at=version.updated_at,
        )
