from collections import defaultdict
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Select
from sqlalchemy.engine import ScalarResult
from sqlalchemy.orm import selectinload

from eneo.assistants.assistant import Assistant
from eneo.assistants.assistant_factory import AssistantFactory
from eneo.database.database import AsyncSession
from eneo.database.tables.assistant_table import (
    AssistantIntegrationKnowledge,
    AssistantMCPServers,
    Assistants,
    AssistantsFiles,
    AssistantsGroups,
    AssistantsWebsites,
)
from eneo.database.tables.assistant_template_table import AssistantTemplates
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.help_assistant_assignment_history_table import (
    HelpAssistantAssignmentHistory,
)
from eneo.database.tables.info_blobs_table import InfoBlobs, active_info_blob_version
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDBModel,
)
from eneo.database.tables.integration_table import (
    UserIntegration as UserIntegrationDBModel,
)
from eneo.database.tables.org_space_assistant_roles_table import (
    OrgSpaceAssistantRoles,
)
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import CrawlRuns, Websites
from eneo.files.file_content_loader import FileAttachmentGroup, FileContentLoader
from eneo.files.file_models import File, FileMetadata, FileType
from eneo.files.file_repo import FileRepository
from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerMapper
from eneo.prompts.prompt import Prompt
from eneo.skills.domain.skill import PersonalDefaultsSnapshot

if TYPE_CHECKING:
    from eneo.collections.domain.collection import Collection
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge as DomainIntegrationKnowledge,
    )
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.websites.domain.website import Website


@dataclass(frozen=True)
class PersonalDefaultValidationInput:
    assistant: Assistant
    configured_mcp_servers: tuple["MCPServer", ...]
    has_knowledge: bool


@dataclass(frozen=True)
class CompletionFileValidationProjection:
    derived_image_metadata: tuple[FileMetadata, ...]
    is_stable: bool


@dataclass(frozen=True)
class AssistantValidationInput:
    assistant: Assistant
    space_is_personal: bool
    configured_mcp_servers: tuple["MCPServer", ...]
    has_knowledge: bool
    derived_image_metadata: tuple[FileMetadata, ...]
    completion_files_stable: bool


def personal_defaults_page_query(
    *,
    tenant_id: UUID,
    limit: int,
    after: tuple[datetime, UUID] | None = None,
) -> Select[tuple[Assistants, bool]]:
    """One keyset page of personal-default candidates, ordered (created_at, id).

    Module-level so the plan test can EXPLAIN exactly the statement production
    executes: the ordering must be served by
    ``ix_assistants_default_created_at_id``, not by re-sorting the tenant's
    remaining rows on every page.
    """
    has_knowledge = sa.or_(
        sa.exists(
            sa.select(sa.literal(1)).where(
                AssistantsGroups.assistant_id == Assistants.id
            )
        ),
        sa.exists(
            sa.select(sa.literal(1)).where(
                AssistantsWebsites.assistant_id == Assistants.id
            )
        ),
        sa.exists(
            sa.select(sa.literal(1)).where(
                AssistantIntegrationKnowledge.assistant_id == Assistants.id
            )
        ),
    ).label("has_knowledge")
    query = (
        sa.select(Assistants, has_knowledge)
        .join(Spaces, Assistants.space_id == Spaces.id)
        .where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_not(None),
            # `== true`, not `.is_(True)`: the partial index predicate is
            # `is_default = true`, and the planner only proves implication
            # when the query uses the same form. `IS TRUE` is a different
            # node and disqualifies the index.
            Assistants.is_default == sa.true(),
        )
        .order_by(Assistants.created_at, Assistants.id)
        .limit(limit + 1)
    )
    if after is not None:
        after_created_at, after_id = after
        query = query.where(
            sa.tuple_(Assistants.created_at, Assistants.id)
            > sa.tuple_(sa.literal(after_created_at), sa.literal(after_id, sa.Uuid()))
        )
    return query


@dataclass(frozen=True)
class PersonalDefaultValidationPage:
    items: list[PersonalDefaultValidationInput]
    # Keyset cursor (created_at, id) of the last row, or None on the last page.
    next_after: tuple[datetime, UUID] | None


# IMPORTANT: every list-returning method in this repo must apply this
# filter. If you add a new list method, either call it here or document
# the explicit exception in a comment on the new method. See PRD §4.
def _exclude_helper_assistants(
    query: Select[tuple[Assistants]],
) -> Select[tuple[Assistants]]:
    """Exclude assistants currently filling a helper role and former helpers.

    Excludes any assistant that:
      (a) has an active row in org_space_assistant_roles, OR
      (b) has any row in help_assistant_assignment_history.

    published=true does NOT override the exclusion — per PRD §4, helper-ness
    is independent of regular publish visibility.
    """
    active_role = sa.select(OrgSpaceAssistantRoles.assistant_id).where(
        OrgSpaceAssistantRoles.assistant_id == Assistants.id
    )
    former_helper = sa.select(HelpAssistantAssignmentHistory.assistant_id).where(
        HelpAssistantAssignmentHistory.assistant_id == Assistants.id
    )
    return query.where(~sa.exists(active_role)).where(~sa.exists(former_helper))


class AssistantRepository:
    def __init__(
        self,
        *,
        session: AsyncSession,
        factory: AssistantFactory,
        file_repo: FileRepository,
        file_content_loader: FileContentLoader,
        completion_model_repo: "CompletionModelRepository",
    ):
        super().__init__()
        self.session = session
        self.factory = factory
        self.file_repo = file_repo
        self.file_content_loader = file_content_loader
        self.completion_model_repo = completion_model_repo

    @staticmethod
    async def get_personal_defaults_snapshot(
        *,
        session: AsyncSession,
        tenant_id: UUID,
    ) -> PersonalDefaultsSnapshot:
        """Return a clock-free version digest for personal-default rows.

        PostgreSQL assigns ``updated_at`` from transaction-start time, so an
        older transaction can commit after a newer one without changing a
        maximum timestamp. ``xmin`` changes on every row update regardless of
        clock ordering.
        """
        row_versions_digest = sa.literal_column(
            "md5(string_agg(assistants.id::text || ':' || "
            "assistants.xmin::text, ',' ORDER BY assistants.id))",
            type_=sa.String(),
        )
        assistant_count, row_versions_digest = (
            await session.execute(
                sa.select(
                    sa.func.count(Assistants.id),
                    row_versions_digest,
                )
                .select_from(Assistants)
                .join(Spaces, Assistants.space_id == Spaces.id)
                .where(
                    Spaces.tenant_id == tenant_id,
                    Spaces.user_id.is_not(None),
                    Assistants.is_default == sa.true(),
                )
            )
        ).one()
        return PersonalDefaultsSnapshot(
            assistant_count=assistant_count,
            row_versions_digest=row_versions_digest,
            runtime_policy_version=None,
        )

    async def _load_attachments(
        self,
        records: Sequence[Assistants],
    ) -> dict[UUID, list[File]]:
        groups = [
            FileAttachmentGroup(
                owner_kind="assistant",
                owner_id=record.id,
                tenant_id=record.user.tenant_id,
                files=tuple(
                    FileMetadata.model_validate(attachment.file)
                    for attachment in record.attachments
                ),
            )
            for record in records
        ]
        loaded = await self.file_content_loader.load_attachment_groups(groups)
        return {record.id: loaded[("assistant", record.id)] for record in records}

    async def project_completion_file_metadata_for_validation(
        self,
        *,
        assistants: Sequence[Assistant],
        models_by_assistant_id: Mapping[UUID, "CompletionModel | None"],
        tenant_id: UUID,
    ) -> dict[UUID, CompletionFileValidationProjection]:
        """Batch-project visible derived-image metadata for validation."""
        metadata_by_assistant_id: dict[UUID, list[FileMetadata]] = {}
        present_ids_by_assistant_id: dict[UUID, set[UUID]] = {}
        assistant_ids_by_parent_id: defaultdict[UUID, list[UUID]] = defaultdict(list)
        parent_ids: list[UUID] = []
        seen_parent_ids: set[UUID] = set()

        for assistant in assistants:
            assert assistant.id is not None
            metadata_by_assistant_id[assistant.id] = []
            present_ids_by_assistant_id[assistant.id] = {
                file.id for file in assistant.attachments
            }
            model = models_by_assistant_id.get(assistant.id)
            if model is None or not model.vision:
                continue
            for file in assistant.attachments:
                if file.file_type is not FileType.TEXT:
                    continue
                assistant_ids_by_parent_id[file.id].append(assistant.id)
                if file.id not in seen_parent_ids:
                    seen_parent_ids.add(file.id)
                    parent_ids.append(file.id)

        unstable_assistant_ids: set[UUID] = set()
        if parent_ids:
            derived_projection = (
                await self.file_repo.project_derived_images_for_attached_roots(
                    parent_ids=parent_ids,
                    tenant_id=tenant_id,
                )
            )
            for metadata in derived_projection.derived_images:
                assert metadata.parent_file_id is not None
                for assistant_id in assistant_ids_by_parent_id[metadata.parent_file_id]:
                    if metadata.id in present_ids_by_assistant_id[assistant_id]:
                        continue
                    metadata_by_assistant_id[assistant_id].append(metadata)
                    present_ids_by_assistant_id[assistant_id].add(metadata.id)
            unstable_assistant_ids = {
                assistant_id
                for parent_id in derived_projection.unstable_parent_ids
                for assistant_id in assistant_ids_by_parent_id[parent_id]
            }

        return {
            assistant_id: CompletionFileValidationProjection(
                derived_image_metadata=tuple(metadata),
                is_stable=assistant_id not in unstable_assistant_ids,
            )
            for assistant_id, metadata in metadata_by_assistant_id.items()
        }

    async def hydrate_completion_files_for_validation(
        self,
        *,
        assistant: Assistant,
        derived_image_metadata: Sequence[FileMetadata],
    ) -> tuple[File, ...]:
        """Hydrate one Assistant's projected derivatives for immediate validation."""
        derived_images = await self.file_content_loader.load(derived_image_metadata)
        return (
            *assistant.attachments,
            *(derived_images[metadata.id] for metadata in derived_image_metadata),
        )

    async def iter_completion_files_for_validation_batches(
        self,
        *,
        validation_inputs: Sequence[AssistantValidationInput],
        tenant_id: UUID,
        max_batch_bytes: int,
    ) -> AsyncIterator[dict[UUID, tuple[File, ...]]]:
        """Hydrate projected derivatives in byte-bounded validation batches."""
        groups: list[FileAttachmentGroup] = []
        validation_input_by_assistant_id: dict[UUID, AssistantValidationInput] = {}
        for validation_input in validation_inputs:
            assistant_id = validation_input.assistant.id
            assert assistant_id is not None
            validation_input_by_assistant_id[assistant_id] = validation_input
            groups.append(
                FileAttachmentGroup(
                    owner_kind="assistant",
                    owner_id=assistant_id,
                    tenant_id=tenant_id,
                    files=validation_input.derived_image_metadata,
                )
            )
        async for (
            derived_images_by_assistant_id
        ) in self.file_content_loader.load_attachment_groups_in_payload_batches(
            groups,
            max_batch_bytes=max_batch_bytes,
        ):
            completion_files_by_assistant_id = {
                assistant_id: (
                    *validation_input_by_assistant_id[
                        assistant_id
                    ].assistant.attachments,
                    *derived_images,
                )
                for (_, assistant_id), derived_images in (
                    derived_images_by_assistant_id.items()
                )
            }
            yield completion_files_by_assistant_id
            del completion_files_by_assistant_id
            del derived_images_by_assistant_id

    @staticmethod
    def _options():
        return [
            selectinload(Assistants.user).selectinload(Users.tenant),
            selectinload(Assistants.user).selectinload(Users.roles),
            selectinload(Assistants.websites)
            .selectinload(Websites.latest_crawl)  # type: ignore[attr-defined]
            .selectinload(CrawlRuns.job),
            selectinload(Assistants.websites).selectinload(Websites.embedding_model),
            selectinload(Assistants.attachments).selectinload(AssistantsFiles.file),
            selectinload(Assistants.template).selectinload(
                AssistantTemplates.completion_model
            ),
            selectinload(Assistants.integration_knowledge_list).selectinload(
                IntegrationKnowledge.embedding_model
            ),
            selectinload(Assistants.integration_knowledge_list)
            .selectinload(IntegrationKnowledge.user_integration)
            .selectinload(UserIntegrationDBModel.tenant_integration)
            .selectinload(TenantIntegrationDBModel.integration),
            selectinload(Assistants.mcp_servers),
            selectinload(Assistants.assistant_mcp_server_tools),
        ]

    async def _set_is_selected_to_false(self, assistant_id: UUID):
        stmt = (
            sa.update(PromptsAssistants)
            .values(is_selected=False)
            .where(PromptsAssistants.assistant_id == assistant_id)
        )

        await self.session.execute(stmt)

    async def _add_assistant_prompt_entry(self, assistant_id: UUID, prompt_id: UUID):
        stmt = (
            sa.insert(PromptsAssistants)
            .values(assistant_id=assistant_id, prompt_id=prompt_id, is_selected=True)
            .returning(PromptsAssistants)
        )

        return await self.session.scalar(stmt)

    async def _get_assistant_prompt_entry(self, assistant_id: UUID, prompt_id: UUID):
        stmt = (
            sa.select(PromptsAssistants)
            .where(PromptsAssistants.prompt_id == prompt_id)
            .where(PromptsAssistants.assistant_id == assistant_id)
        )

        return await self.session.scalar(stmt)

    async def _select_assistant_prompt_entry(self, assistant_id: UUID, prompt_id: UUID):
        stmt = (
            sa.update(PromptsAssistants)
            .where(PromptsAssistants.prompt_id == prompt_id)
            .where(PromptsAssistants.assistant_id == assistant_id)
            .values(is_selected=True)
        )

        await self.session.execute(stmt)

    async def _add_prompt(self, assistant_id: UUID, prompt: Prompt):
        assert prompt.id is not None, "Prompt must have been persisted before linking"
        await self._set_is_selected_to_false(assistant_id=assistant_id)

        prompt_assistant_entry = await self._get_assistant_prompt_entry(
            assistant_id=assistant_id, prompt_id=prompt.id
        )

        if prompt_assistant_entry is not None:
            await self._select_assistant_prompt_entry(
                assistant_id=assistant_id, prompt_id=prompt.id
            )
        else:
            await self._add_assistant_prompt_entry(
                assistant_id=assistant_id, prompt_id=prompt.id
            )

        return prompt

    async def _get_selected_prompt(self, assistant_id: UUID):
        stmt = (
            sa.select(Prompts)
            .join(PromptsAssistants)
            .where(PromptsAssistants.prompt_id == Prompts.id)
            .where(PromptsAssistants.assistant_id == assistant_id)
            .where(PromptsAssistants.is_selected)
            .options(selectinload(Prompts.user))
        )

        return await self.session.scalar(stmt)

    async def _set_attachments(
        self, assistant_in_db: Assistants, attachments: list[File]
    ):
        # Delete all
        stmt = sa.delete(AssistantsFiles).where(
            AssistantsFiles.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        # Add attachments
        if attachments:
            attachments_dicts = [
                dict(assistant_id=assistant_in_db.id, file_id=file.id)
                for file in attachments
            ]

            stmt = sa.insert(AssistantsFiles).values(attachments_dicts)
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _set_collections(
        self, assistant_in_db: Assistants, collections: list["Collection"]
    ):
        # Delete all
        stmt = sa.delete(AssistantsGroups).where(
            AssistantsGroups.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        if collections:
            stmt = sa.insert(AssistantsGroups).values(
                [
                    dict(group_id=group.id, assistant_id=assistant_in_db.id)
                    for group in collections
                ]
            )
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _set_websites(
        self, assistant_in_db: Assistants, websites: list["Website"]
    ):
        # Delete all
        stmt = sa.delete(AssistantsWebsites).where(
            AssistantsWebsites.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        if websites:
            stmt = sa.insert(AssistantsWebsites).values(
                [
                    dict(website_id=website.id, assistant_id=assistant_in_db.id)
                    for website in websites
                ]
            )
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _set_integration_knowledge(
        self,
        assistant_in_db: Assistants,
        integration_knowledge: list["DomainIntegrationKnowledge"],
    ):
        # Delete all
        stmt = sa.delete(AssistantIntegrationKnowledge).where(
            AssistantIntegrationKnowledge.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        if integration_knowledge:
            stmt = sa.insert(AssistantIntegrationKnowledge).values(
                [
                    dict(
                        integration_knowledge_id=knowledge.id,
                        assistant_id=assistant_in_db.id,
                    )
                    for knowledge in integration_knowledge
                ]
            )
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def set_mcp_servers(
        self,
        assistant_in_db: Assistants,
        mcp_server_ids: list[UUID],
    ):
        """Set MCP server associations for an assistant.

        Args:
            assistant_in_db: The assistant database record
            mcp_server_ids: List of MCP server IDs to associate
        """
        # Delete all existing associations
        stmt = sa.delete(AssistantMCPServers).where(
            AssistantMCPServers.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        await self._prune_mcp_tool_overrides_for_servers(
            assistant_in_db=assistant_in_db,
            mcp_server_ids=mcp_server_ids,
        )

        if mcp_server_ids:
            values = [
                {
                    "assistant_id": assistant_in_db.id,
                    "mcp_server_id": server_id,
                }
                for server_id in mcp_server_ids
            ]

            stmt = sa.insert(AssistantMCPServers).values(values)
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _prune_mcp_tool_overrides_for_servers(
        self,
        *,
        assistant_in_db: Assistants,
        mcp_server_ids: list[UUID],
    ) -> None:
        """Keep assistant tool overrides inside the selected server set."""
        from eneo.database.tables.assistant_table import AssistantMCPServerTools
        from eneo.database.tables.mcp_server_table import (
            MCPServerTools as MCPServerToolsTable,
        )

        stmt = sa.delete(AssistantMCPServerTools).where(
            AssistantMCPServerTools.assistant_id == assistant_in_db.id
        )
        if mcp_server_ids:
            selected_tool_ids = sa.select(MCPServerToolsTable.id).where(
                MCPServerToolsTable.mcp_server_id.in_(mcp_server_ids)
            )
            stmt = stmt.where(
                ~AssistantMCPServerTools.mcp_server_tool_id.in_(selected_tool_ids)
            )
        await self.session.execute(stmt)

    async def _set_mcp_tools(
        self,
        assistant_in_db: Assistants,
        mcp_tool_settings: list[tuple[UUID, bool]],
    ):
        """Set MCP tool overrides for an assistant.

        Args:
            assistant_in_db: The assistant database record
            mcp_tool_settings: List of (tool_id, is_enabled) tuples
        """
        from eneo.database.tables.assistant_table import AssistantMCPServerTools

        # Delete all existing tool overrides
        stmt = sa.delete(AssistantMCPServerTools).where(
            AssistantMCPServerTools.assistant_id == assistant_in_db.id
        )
        await self.session.execute(stmt)

        if mcp_tool_settings:
            from eneo.database.tables.mcp_server_table import (
                MCPServerTools as MCPServerToolsTable,
            )

            server_ids_stmt = sa.select(AssistantMCPServers.mcp_server_id).where(
                AssistantMCPServers.assistant_id == assistant_in_db.id
            )
            server_ids_result = await self.session.execute(server_ids_stmt)
            valid_server_ids = [row[0] for row in server_ids_result.fetchall()]

            tool_ids = [tool_id for tool_id, _ in mcp_tool_settings]
            if tool_ids and valid_server_ids:
                valid_tool_ids_stmt = sa.select(MCPServerToolsTable.id).where(
                    MCPServerToolsTable.id.in_(tool_ids),
                    MCPServerToolsTable.mcp_server_id.in_(valid_server_ids),
                )
                valid_tool_ids_result = await self.session.execute(valid_tool_ids_stmt)
                valid_tool_ids = {row[0] for row in valid_tool_ids_result.fetchall()}
            else:
                valid_tool_ids: set[UUID] = set()

            invalid_tool_ids = [
                str(tool_id) for tool_id in tool_ids if tool_id not in valid_tool_ids
            ]
            if invalid_tool_ids:
                raise BadRequestException(
                    "MCP tool override references tool(s) outside assistant MCP servers: "
                    + ", ".join(invalid_tool_ids)
                )

            values = [
                {
                    "assistant_id": assistant_in_db.id,
                    "mcp_server_tool_id": tool_id,
                    "is_enabled": is_enabled,
                }
                for tool_id, is_enabled in mcp_tool_settings
            ]

            stmt = sa.insert(AssistantMCPServerTools).values(values)
            await self.session.execute(stmt)

        await self.session.refresh(assistant_in_db)

    async def _get_groups(self, assistant_id: UUID):
        query = (
            sa.select(
                CollectionsTable,
                sa.func.coalesce(sa.func.count(InfoBlobs.id).label("infoblob_count")),
            )
            .outerjoin(
                InfoBlobs,
                sa.and_(
                    CollectionsTable.id == InfoBlobs.group_id,
                    active_info_blob_version(),
                ),
            )
            .outerjoin(
                AssistantsGroups, AssistantsGroups.group_id == CollectionsTable.id
            )
            .where(AssistantsGroups.assistant_id == assistant_id)
            .group_by(CollectionsTable.id)
            .order_by(CollectionsTable.created_at)
            .options(selectinload(CollectionsTable.embedding_model))
        )

        res = await self.session.execute(query)
        return res.all()

    async def get_record_with_options(
        self, query: Select[tuple[Assistants]]
    ) -> Assistants | None:
        for option in self._options():
            query = query.options(option)

        return await self.session.scalar(query)

    async def get_records_with_options(
        self, query: Select[tuple[Assistants]]
    ) -> ScalarResult[Assistants]:
        for option in self._options():
            query = query.options(option)

        return await self.session.scalars(query)

    async def add(self, assistant: Assistant):
        completion_model_id = (
            assistant.completion_model.id
            if assistant.completion_model is not None
            else None
        )

        template_id = (
            assistant.source_template.id if assistant.source_template else None
        )
        assert assistant.user is not None
        query = (
            sa.insert(Assistants)
            .values(
                id=assistant.id,
                name=assistant.name,
                user_id=assistant.user.id,
                completion_model_id=completion_model_id,
                completion_model_kwargs=assistant.completion_model_kwargs.model_dump(),
                logging_enabled=assistant.logging_enabled,
                hidden=assistant.hidden,
                origin=assistant.origin.value,
                managing_flow_id=assistant.managing_flow_id,
                guardrail_active=False,
                space_id=assistant.space_id,
                is_default=assistant.is_default,
                published=assistant.published,
                template_id=template_id,
                type=assistant.type,
                description=assistant.description,
            )
            .returning(Assistants)
        )
        entry_in_db = await self.session.scalar(query)
        assert entry_in_db is not None

        # Assign groups and websites
        await self._set_collections(entry_in_db, assistant.collections)
        await self._set_websites(entry_in_db, assistant.websites)
        await self._set_attachments(entry_in_db, attachments=assistant.attachments)

        if assistant.prompt:
            await self._add_prompt(assistant_id=entry_in_db.id, prompt=assistant.prompt)

    async def get_for_user(
        self,
        user_id: UUID,
        search_query: str | None = None,
        space_id: UUID | None = None,
        assistant_id: UUID | None = None,
    ):
        query = (
            sa.select(Assistants)
            .where(Assistants.user_id == user_id)
            .order_by(Assistants.created_at)
        )

        if assistant_id is not None:
            query = query.where(Assistants.id == assistant_id)
        elif space_id is not None:
            query = query.where(Assistants.space_id == space_id)

        if search_query is not None:
            query = query.filter(Assistants.name.like(f"%{search_query}%"))

        query = _exclude_helper_assistants(query)

        records = list(await self.get_records_with_options(query))
        attachments = await self._load_attachments(records)

        completion_models = await self.completion_model_repo.all()

        return [
            self.factory.create_assistant_from_db(
                record,
                attachments=attachments[record.id],
                completion_model_list=completion_models,
            )
            for record in records
        ]

    async def get_for_tenant(
        self,
        tenant_id: UUID,
        search_query: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ):
        query = (
            sa.select(Assistants)
            .join(Users)
            .where(Users.tenant_id == tenant_id)
            .order_by(Assistants.created_at)
        )

        if start_date is not None:
            query = query.filter(Assistants.created_at >= start_date)

        if end_date is not None:
            query = query.filter(Assistants.created_at <= end_date)

        if search_query is not None:
            query = query.filter(Assistants.name.like(f"%{search_query}%"))

        query = _exclude_helper_assistants(query)

        records = list(await self.get_records_with_options(query))
        attachments = await self._load_attachments(records)
        completion_models = await self.completion_model_repo.all()

        return [
            self.factory.create_assistant_from_db(
                record,
                attachments=attachments[record.id],
                completion_model_list=completion_models,
            )
            for record in records
        ]

    async def get_personal_defaults_page(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        after: tuple[datetime, UUID] | None = None,
    ) -> PersonalDefaultValidationPage:
        """Load one keyset page of the persisted baselines affected by
        personal-chat governance.

        This deliberately does not apply the helper-assistant exclusion used by
        user-facing lists: governance must validate every personal default row,
        even if an unrelated role assignment has left one in an invalid state.

        Paged because the caller walks entire tenants: one unbounded load with
        five eager collections per row materialises the whole fleet in memory.
        The cursor is ``(created_at, id)`` — ``created_at`` alone is not unique,
        and a non-deterministic order would let rows slip between pages.
        """
        query = personal_defaults_page_query(
            tenant_id=tenant_id, limit=limit, after=after
        ).options(
            selectinload(Assistants.user).selectinload(Users.tenant),
            selectinload(Assistants.user).selectinload(Users.roles),
            selectinload(Assistants.attachments).selectinload(AssistantsFiles.file),
            selectinload(Assistants.template).selectinload(
                AssistantTemplates.completion_model
            ),
            selectinload(Assistants.mcp_servers),
        )
        rows = list((await self.session.execute(query)).all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        records = [row[0] for row in rows]
        if not records:
            return PersonalDefaultValidationPage(items=[], next_after=None)

        prompt_rows = (
            await self.session.execute(
                sa.select(Prompts, PromptsAssistants.assistant_id)
                .join(PromptsAssistants)
                .where(
                    PromptsAssistants.assistant_id.in_(
                        [record.id for record in records]
                    ),
                    PromptsAssistants.is_selected,
                )
                .options(selectinload(Prompts.user))
            )
        ).all()
        prompts_by_assistant = {
            assistant_id: prompt for prompt, assistant_id in prompt_rows
        }
        completion_models = await self.completion_model_repo.all()
        attachments = await self._load_attachments(records)

        items = [
            PersonalDefaultValidationInput(
                assistant=self.factory.create_assistant_from_db(
                    record,
                    attachments=attachments[record.id],
                    completion_model_list=completion_models,
                    prompt=prompts_by_assistant.get(record.id),
                ),
                configured_mcp_servers=tuple(
                    MCPServerMapper.to_entities(record.mcp_servers)
                ),
                has_knowledge=row[1],
            )
            for row, record in zip(rows, records, strict=True)
        ]
        last = records[-1]
        return PersonalDefaultValidationPage(
            items=items,
            next_after=(last.created_at, last.id) if has_more else None,
        )

    async def get_by_ids_for_validation(
        self,
        *,
        tenant_id: UUID,
        assistant_ids: Sequence[UUID],
    ) -> dict[UUID, AssistantValidationInput]:
        """Load a bounded set of Assistants for save-equivalent fit validation."""
        if not assistant_ids:
            return {}
        has_knowledge = sa.or_(
            sa.exists(
                sa.select(sa.literal(1)).where(
                    AssistantsGroups.assistant_id == Assistants.id
                )
            ),
            sa.exists(
                sa.select(sa.literal(1)).where(
                    AssistantsWebsites.assistant_id == Assistants.id
                )
            ),
            sa.exists(
                sa.select(sa.literal(1)).where(
                    AssistantIntegrationKnowledge.assistant_id == Assistants.id
                )
            ),
        ).label("has_knowledge")
        query = (
            sa.select(Assistants, Spaces.user_id.is_not(None), has_knowledge)
            .join(Spaces, Spaces.id == Assistants.space_id)
            .where(
                Spaces.tenant_id == tenant_id,
                Assistants.id.in_(assistant_ids),
            )
            .options(
                selectinload(Assistants.user).selectinload(Users.tenant),
                selectinload(Assistants.user).selectinload(Users.roles),
                selectinload(Assistants.attachments).selectinload(AssistantsFiles.file),
                selectinload(Assistants.template).selectinload(
                    AssistantTemplates.completion_model
                ),
                selectinload(Assistants.mcp_servers),
            )
        )
        rows = list((await self.session.execute(query)).all())
        records = [row[0] for row in rows]
        if not records:
            return {}
        prompt_rows = (
            await self.session.execute(
                sa.select(Prompts, PromptsAssistants.assistant_id)
                .join(PromptsAssistants)
                .where(
                    PromptsAssistants.assistant_id.in_(
                        [record.id for record in records]
                    ),
                    PromptsAssistants.is_selected,
                )
                .options(selectinload(Prompts.user))
            )
        ).all()
        prompts_by_assistant = {
            assistant_id: prompt for prompt, assistant_id in prompt_rows
        }
        completion_models = await self.completion_model_repo.all(with_deprecated=True)
        attachments = await self._load_attachments(records)

        assistants_by_id = {
            record.id: self.factory.create_assistant_from_db(
                record,
                attachments=attachments[record.id],
                completion_model_list=completion_models,
                prompt=prompts_by_assistant.get(record.id),
            )
            for record in records
        }
        completion_file_projections = (
            await self.project_completion_file_metadata_for_validation(
                assistants=list(assistants_by_id.values()),
                models_by_assistant_id={
                    assistant_id: assistant.completion_model
                    for assistant_id, assistant in assistants_by_id.items()
                },
                tenant_id=tenant_id,
            )
        )

        inputs: dict[UUID, AssistantValidationInput] = {}
        for record, space_is_personal, record_has_knowledge in rows:
            assistant = assistants_by_id[record.id]
            configured_mcp_servers = tuple(
                MCPServerMapper.to_entities(record.mcp_servers)
            )
            inputs[record.id] = AssistantValidationInput(
                assistant=assistant,
                space_is_personal=space_is_personal,
                configured_mcp_servers=configured_mcp_servers,
                has_knowledge=record_has_knowledge,
                derived_image_metadata=completion_file_projections[
                    record.id
                ].derived_image_metadata,
                completion_files_stable=completion_file_projections[
                    record.id
                ].is_stable,
            )
        return inputs

    async def update(
        self,
        assistant: Assistant,
        mcp_server_ids: list[UUID] | None = None,
        mcp_tool_settings: list[tuple[UUID, bool]] | None = None,
    ):
        completion_model_id = (
            assistant.completion_model.id
            if assistant.completion_model is not None
            else None
        )
        query = (
            sa.update(Assistants)
            .values(
                name=assistant.name,
                completion_model_id=completion_model_id,
                completion_model_kwargs=assistant.completion_model_kwargs.model_dump(),
                logging_enabled=assistant.logging_enabled,
                hidden=assistant.hidden,
                origin=assistant.origin.value,
                managing_flow_id=assistant.managing_flow_id,
                space_id=assistant.space_id,
                published=assistant.published,
                description=assistant.description,
                type=assistant.type,
                insight_enabled=assistant.insight_enabled,
                data_retention_days=assistant.data_retention_days,
                metadata_json=assistant.metadata_json,
                icon_id=assistant.icon_id,
            )
            .where(Assistants.id == assistant.id)
            .returning(Assistants)
        )
        entry_in_db = await self.session.scalar(query)
        assert entry_in_db is not None

        # assign groups and websites
        await self._set_collections(entry_in_db, assistant.collections)
        await self._set_websites(entry_in_db, assistant.websites)
        await self._set_integration_knowledge(
            entry_in_db, assistant.integration_knowledge_list
        )
        await self._set_attachments(entry_in_db, assistant.attachments)

        # Set MCP servers/tool overrides explicitly when provided by caller.
        # Backward-compatible fallback to legacy side-channel attributes.
        effective_mcp_server_ids = mcp_server_ids
        if effective_mcp_server_ids is None:
            assistant_mcp_server_ids = cast(
                list[UUID] | None, getattr(assistant, "_mcp_server_ids", None)
            )
            if assistant_mcp_server_ids is not None:
                effective_mcp_server_ids = assistant_mcp_server_ids

        effective_mcp_tool_settings = mcp_tool_settings
        if effective_mcp_tool_settings is None:
            assistant_mcp_tool_settings = cast(
                list[tuple[UUID, bool]] | None,
                getattr(assistant, "_mcp_tool_settings", None),
            )
            if assistant_mcp_tool_settings is not None:
                effective_mcp_tool_settings = assistant_mcp_tool_settings

        if effective_mcp_server_ids is not None:
            await self.set_mcp_servers(entry_in_db, effective_mcp_server_ids)
        if effective_mcp_tool_settings is not None:
            await self._set_mcp_tools(entry_in_db, effective_mcp_tool_settings)

        if assistant.prompt:
            await self._add_prompt(assistant_id=entry_in_db.id, prompt=assistant.prompt)
