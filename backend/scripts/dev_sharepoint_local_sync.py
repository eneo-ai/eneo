#!/usr/bin/env python3
"""Sync a local folder into a space as if it were a SharePoint source.

Development only. Seeds a fixture SharePoint integration for the user, creates
(or reuses) an integration knowledge source in the given space and runs the
real full-sync code with the Graph client replaced by a directory walk. Re-run
after editing files in the folder to exercise versions, backfill and the
tabular policy.

Usage (inside the devcontainer):
    uv run python scripts/dev_sharepoint_local_sync.py \\
        --space-id <uuid> --user-email you@example.com --files-dir ./sheets \\
        [--name "Local SharePoint"] [--policy index_and_tool|tool_only]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4, uuid5

import sqlalchemy as sa
from dependency_injector import providers

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "src"))

from eneo.database.database import sessionmanager  # noqa: E402
from eneo.database.tables.ai_models_table import EmbeddingModels  # noqa: E402
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks  # noqa: E402
from eneo.database.tables.info_blobs_table import InfoBlobs  # noqa: E402
from eneo.database.tables.integration_table import (  # noqa: E402
    IntegrationKnowledge as IntegrationKnowledgeTable,
)
from eneo.database.tables.spaces_table import Spaces  # noqa: E402
from eneo.database.tables.users_table import Users  # noqa: E402
from eneo.info_blobs.info_blob_repo import InfoBlobRepository  # noqa: E402
from eneo.integration.domain.entities.integration import Integration  # noqa: E402
from eneo.integration.domain.entities.integration_knowledge import (  # noqa: E402
    IntegrationKnowledge,
)
from eneo.integration.domain.entities.tenant_integration import (  # noqa: E402
    TenantIntegration,
)
from eneo.integration.domain.entities.user_integration import (  # noqa: E402
    UserIntegration,
)
from eneo.integration.domain.tabular_policy import TabularPolicy  # noqa: E402
from eneo.integration.infrastructure.content_service import (  # noqa: E402
    sharepoint_content_service as service_module,
)
from eneo.main.config import get_settings  # noqa: E402
from eneo.main.container.container import Container  # noqa: E402
from eneo.main.container.container_overrides import override_user  # noqa: E402
from eneo.object_content.runtime import object_content_runtime  # noqa: E402
from eneo.settings.encryption_service import EncryptionService  # noqa: E402
from tests.integration.fixtures.sharepoint_local_client import (  # noqa: E402
    FIXTURE_DRIVE_ID,
    FIXTURE_ROOT_ID,
    FIXTURE_WEB_ORIGIN,
    LocalFolderSharePointClient,
)

_NAMESPACE = UUID("8f1d2d3e-5a6b-4c7d-8e9f-0a1b2c3d4e5f")


def _fixture_id(*parts: object) -> UUID:
    return uuid5(_NAMESPACE, ":".join(str(part) for part in parts))


async def _get_or_add(repo, entity, *, id: UUID):
    existing = await repo.one_or_none(id=id)
    return existing if existing is not None else await repo.add(entity)


async def _ensure_source(
    container, *, space_id: UUID, name: str, policy: TabularPolicy
):
    user = container.user()
    session = container.session()
    space = await session.get(Spaces, space_id)
    if space is None or space.tenant_id != user.tenant_id:
        raise SystemExit(f"Space {space_id} not found in the user's tenant")

    knowledge_repo = container.integration_knowledge_repo()
    existing_id = await session.scalar(
        sa.select(IntegrationKnowledgeTable.id).where(
            IntegrationKnowledgeTable.space_id == space_id,
            IntegrationKnowledgeTable.name == name,
            IntegrationKnowledgeTable.drive_id == FIXTURE_DRIVE_ID,
        )
    )
    if existing_id is not None:
        existing = await knowledge_repo.one(id=existing_id)
        if existing.tabular_policy != policy:
            existing.tabular_policy = policy
            existing = await knowledge_repo.update(existing)
        return existing, False

    integration = await _get_or_add(
        container.integration_repo(),
        Integration(
            id=_fixture_id("integration"),
            name="SharePoint",
            description="Local folder fixture",
            integration_type="sharepoint",
        ),
        id=_fixture_id("integration"),
    )
    tenant_integration = await _get_or_add(
        container.tenant_integration_repo(),
        TenantIntegration(
            id=_fixture_id("tenant", user.tenant_id),
            tenant_id=user.tenant_id,
            integration=integration,
        ),
        id=_fixture_id("tenant", user.tenant_id),
    )
    user_integration = await _get_or_add(
        container.user_integration_repo(),
        UserIntegration(
            id=_fixture_id("user", user.id),
            tenant_integration=tenant_integration,
            user_id=user.id,
            authenticated=True,
        ),
        id=_fixture_id("user", user.id),
    )
    model_row = (
        await session.scalar(
            sa.select(EmbeddingModels)
            .where(EmbeddingModels.tenant_id == user.tenant_id)
            .limit(1)
        )
        or (await session.scalars(sa.select(EmbeddingModels).limit(1))).one()
    )
    embedding_model = await container.embedding_model_repo2().one(model_id=model_row.id)
    knowledge = await knowledge_repo.add(
        obj=IntegrationKnowledge(
            name=name,
            user_integration=user_integration,
            embedding_model=embedding_model,
            tenant_id=user.tenant_id,
            space_id=space_id,
            url=FIXTURE_WEB_ORIGIN,
            drive_id=FIXTURE_DRIVE_ID,
            folder_id=FIXTURE_ROOT_ID,
            resource_type="onedrive",
            selected_item_type="folder",
            tabular_policy=policy,
        )
    )
    return knowledge, True


async def _report(session, knowledge_id: UUID) -> None:
    repo = InfoBlobRepository(session)
    rows = (
        await session.execute(
            sa.select(
                InfoBlobs.id,
                InfoBlobs.title,
                InfoBlobs.version_state,
                InfoBlobs.source_id,
            )
            .where(InfoBlobs.integration_knowledge_id == knowledge_id)
            .order_by(InfoBlobs.title, InfoBlobs.created_at)
        )
    ).all()
    versions: dict[UUID, int] = {}
    for row in rows:
        versions[row.source_id] = versions.get(row.source_id, 0) + 1
    originals = await repo.get_originals([row.id for row in rows])
    print(f"\n{'document':40} {'state':11} {'versions':>8} {'chunks':>6}  original")
    for row in rows:
        if row.version_state != "active":
            continue
        chunks = await session.scalar(
            sa.select(sa.func.count()).where(InfoBlobChunks.info_blob_id == row.id)
        )
        original = originals.get(row.id)
        tag = (
            f"{original.sha256.hex()[:12]} ({original.media_type})"
            if original is not None and original.usable
            else "-"
        )
        print(
            f"{(row.title or '')[:40]:40} {row.version_state:11} {versions[row.source_id]:>8} {chunks:>6}  {tag}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--space-id", type=UUID, required=True)
    parser.add_argument("--user-email", required=True, help="The user the sync runs as")
    parser.add_argument("--files-dir", type=Path, required=True)
    parser.add_argument("--name", default="Local SharePoint")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Acknowledge that this writes a fixture SharePoint integration and "
            "source into the configured database"
        ),
    )
    parser.add_argument(
        "--policy",
        choices=[p.value for p in TabularPolicy],
        default=TabularPolicy.INDEX_AND_TOOL.value,
    )
    args = parser.parse_args()

    settings = get_settings()
    database = settings.database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not args.confirm:
        raise SystemExit(
            f"This writes a fixture SharePoint source into database '{database}'. "
            "Re-run with --confirm on a development database."
        )
    print(f"Database: {database}")
    folder = args.files_dir.resolve()
    if not folder.is_dir():
        raise SystemExit(f"{folder} is not a directory")

    sessionmanager.init(settings.database_url)
    # Same bootstrap as the server: the administrator-managed object store
    # connection lives in PostgreSQL behind the deployment's encryption key.
    object_content_runtime.start(
        encryption=EncryptionService(
            None if settings.testing else settings.encryption_key
        )
    )
    await object_content_runtime.validate_configuration()
    try:
        async with sessionmanager.session() as session, session.begin():
            container = Container(session=providers.Object(session))
            user_row = await session.scalar(
                sa.select(Users).where(Users.email == args.user_email)
            )
            if user_row is None:
                raise SystemExit(f"No user with email {args.user_email}")
            user = await container.user_repo().get_user_by_id(id=user_row.id)
            assert user is not None
            override_user(container=container, user=user)

            knowledge, created = await _ensure_source(
                container,
                space_id=args.space_id,
                name=args.name,
                policy=TabularPolicy(args.policy),
            )
            print(
                f"{'Created' if created else 'Reusing'} source '{knowledge.name}' ({knowledge.id}), policy {knowledge.tabular_policy.value}"
            )

            service_module.SharePointContentClient = (  # type: ignore[misc]
                lambda **kwargs: LocalFolderSharePointClient(root=folder, **kwargs)
            )
            service = container.sharepoint_content_service()
            service.oauth_token_repo.one = AsyncMock(  # type: ignore[method-assign]
                return_value=SimpleNamespace(
                    id=uuid4(),
                    access_token="fixture",
                    base_url=FIXTURE_WEB_ORIGIN,
                    is_sharepoint=True,
                )
            )
            result = await service.pull_content(
                token_id=uuid4(),
                integration_knowledge_id=knowledge.id,
                drive_id=FIXTURE_DRIVE_ID,
                folder_id=FIXTURE_ROOT_ID,
                resource_type="onedrive",
            )
            print(f"Sync result: {result}")
            await _report(session, knowledge.id)
    finally:
        await object_content_runtime.stop()
        await sessionmanager.close()


if __name__ == "__main__":
    asyncio.run(main())
