# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from intric.prompt_library.domain.prompt_library import PromptLibraryEntry
from intric.prompt_library.presentation.prompt_library_models import (
    PromptLibraryEntryPublic,
    PromptLibraryEntrySparse,
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
            created_by_user_id=entry.created_by_user_id,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )
