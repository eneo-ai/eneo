from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, List, Literal, TypeVar
from urllib.parse import quote
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import InstrumentedAttribute, defer, selectinload
from sqlalchemy.sql.elements import ColumnElement

from eneo.database.affected_rows import affected_row_count
from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.database.tables.info_blobs_table import (
    InfoBlobs,
    InfoBlobVersionState,
    active_info_blob_version,
    website_navigation_path,
    website_path_below,
    website_source_url_equals,
)
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.object_content_table import (
    InfoBlobContentReferences,
    ObjectContents,
)
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import Websites
from eneo.info_blobs.info_blob import (
    InfoBlobAdd,
    InfoBlobAddToDB,
    InfoBlobInDB,
    InfoBlobInDBNoText,
    InfoBlobUpdate,
)
from eneo.main.exceptions import (
    InfoBlobPublicationConflictError,
    NotFoundException,
)
from eneo.object_content.content import ContentAccessClass, ContentState
from eneo.websites.domain.source_url import normalize_url

_InfoBlobNoTextT = TypeVar("_InfoBlobNoTextT", bound=InfoBlobInDBNoText)


@dataclass(frozen=True, slots=True)
class InfoBlobOriginal:
    content_id: UUID
    tenant_id: UUID
    sha256: bytes
    access_class: ContentAccessClass
    state: ContentState
    original_filename: str

    @property
    def usable(self) -> bool:
        return self.state is ContentState.AVAILABLE


@dataclass(frozen=True, slots=True)
class InfoBlobPublication:
    info_blob: InfoBlobInDB
    original: InfoBlobOriginal | None


@dataclass(frozen=True, slots=True)
class ReplacedPage:
    """A page of replaced versions in id order, and which still hold chunks."""

    last_id: UUID | None
    versions_read: int
    with_search_data: list[UUID]


@dataclass(frozen=True, slots=True)
class ReplacedBatch:
    last_scanned_id: UUID | None
    versions_read: int
    released_versions: int
    released_bytes: int
    skipped_busy: int


@dataclass(frozen=True, slots=True)
class ActiveUpload:
    """The active version an upload to a collection would refresh or replace."""

    info_blob_id: UUID
    embedding_model_id: UUID | None
    original_sha256: bytes | None


@dataclass(frozen=True, slots=True)
class InfoBlobListing:
    """One document's identity, without its text.

    Listing a source means reading hundreds of rows whose ``text`` column is
    TOASTed; hydrating full entities for a title list would move megabytes to
    render kilobytes.
    """

    id: UUID
    title: str | None
    url: str | None

    @property
    def label(self) -> str:
        return self.title or self.url or "Untitled source"


@dataclass(frozen=True, slots=True)
class WebsiteInfoBlobPage:
    items: list[InfoBlobInDBNoText]
    total_count: int
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class WebsiteContentFolder:
    """A URL prefix, not a page-to-document ownership relationship."""

    path: str
    count: int
    has_children: bool


@dataclass(frozen=True, slots=True)
class WebsiteContentFolderPage:
    items: list[WebsiteContentFolder]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class IntegrationDocumentsPage:
    items: list[InfoBlobInDBNoText]
    total_count: int
    total_size: int


IntegrationDocumentSort = Literal["name", "path", "size", "updated_at"]
_Column = ColumnElement[Any] | InstrumentedAttribute[Any]
_LIKE_ESCAPE = "\\"


def _like_literal(needle: str) -> str:
    return (
        needle.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )


def _contains(column: _Column, needle: str) -> ColumnElement[bool]:
    return column.ilike(f"%{_like_literal(needle)}%", escape=_LIKE_ESCAPE)


def _starts_with(column: _Column, prefix: str) -> ColumnElement[bool]:
    return column.ilike(f"{_like_literal(prefix)}%", escape=_LIKE_ESCAPE)


# Every property value except booleans'. In lax mode ``value[*]`` yields a
# plain value as well as each entry of a multi-value list. An entry without a
# kind is kept: ``@.kind == "boolean"`` is false when the key is missing.
_SEARCHABLE_PROPERTY_VALUES_PATH = '$[*] ? (!(@.kind == "boolean")).value[*]'


def _property_value_matches(q: str) -> ColumnElement[bool]:
    """``q`` in a value of the document's ``source_metadata``.

    Only values are searched: every document of a library shares the same
    property names and labels, so matching those would match them all.
    Booleans are left out as well: they are stored as "true" and "false" but
    shown as yes and no, so "true" would match every document of a library
    with a yes/no column. A date-only value is shown as the date part of its
    stored ISO form, so it matches as shown.
    """
    values = sa.func.jsonb_array_elements_text(
        sa.func.jsonb_path_query_array(
            InfoBlobs.source_metadata,
            sa.literal_column(f"'{_SEARCHABLE_PROPERTY_VALUES_PATH}'"),
        )
    ).column_valued("value", joins_implicitly=True)
    return sa.exists().where(_contains(values, q))


def _title_or_path_matches(q: str, url_anchor: str | None) -> ColumnElement[bool]:
    """``q`` in the title, or in the URL below the item's own URL.

    Document URLs are percent-encoded, so the encoded form of ``q`` is tried
    as well. Only the part after ``url_anchor`` (the item's site, library or
    folder URL) is searched, so a site named KS does not match every document
    under /sites/KS. Items without a stored URL fall back to the whole URL, as
    do documents whose URL no longer starts with the anchor: a sync refreshes
    document URLs after the selected folder was renamed, but not the item's
    own URL, and cutting the old anchor's width out of a shorter URL would
    hide part of a nested folder name.
    """
    path: _Column = InfoBlobs.url
    if url_anchor:
        path = sa.case(
            (
                _starts_with(InfoBlobs.url, url_anchor),
                sa.func.substring(InfoBlobs.url, len(url_anchor) + 1),
            ),
            else_=InfoBlobs.url,
        )
    return _title_or_url_matches(q, path)


def _title_or_url_matches(
    q: str, path: _Column | ColumnElement[str]
) -> ColumnElement[bool]:
    """``q`` in the title, or in ``path``: the searchable part of the URL."""
    needles = [q]
    if (encoded := quote(q, safe="/")) != q:
        needles.append(encoded)
    return sa.or_(
        _contains(InfoBlobs.title, q), *(_contains(path, needle) for needle in needles)
    )


def _document_matches(q: str, url_anchor: str | None) -> ColumnElement[bool]:
    return sa.or_(_title_or_path_matches(q, url_anchor), _property_value_matches(q))


def _document_sort_keys(sort: IntegrationDocumentSort) -> list[_Column]:
    if sort == "name":
        return [InfoBlobs.title]
    if sort == "size":
        return [InfoBlobs.size]
    if sort == "updated_at":
        return [InfoBlobs.updated_at]
    # The URL without its file name orders documents by folder; within one
    # item every URL shares the same prefix, so this equals their relative path.
    return [sa.func.regexp_replace(InfoBlobs.url, "/[^/]*$", ""), InfoBlobs.title]


class InfoBlobRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[InfoBlobInDB] = BaseRepositoryDelegate(
            session,
            InfoBlobs,
            InfoBlobInDB,
            with_options=[
                selectinload(InfoBlobs.group),
                selectinload(InfoBlobs.group).selectinload(
                    CollectionsTable.embedding_model
                ),
                selectinload(InfoBlobs.embedding_model),
                selectinload(InfoBlobs.website),
            ],
        )
        self.session = session

    async def _get_group(self, group_id: UUID):
        stmt = sa.select(CollectionsTable).where(CollectionsTable.id == group_id)
        group = await self.session.scalar(stmt)

        return group

    async def _get_website(self, website_id: UUID):
        stmt = sa.select(Websites).where(Websites.id == website_id)
        website = await self.session.scalar(stmt)

        return website

    async def _get_integration_knowledge(self, knowledge_id: UUID):
        stmt = sa.select(IntegrationKnowledge).where(
            IntegrationKnowledge.id == knowledge_id
        )
        knowledge = await self.session.scalar(stmt)

        return knowledge

    async def get_by_ids(self, ids: list[UUID]) -> list[InfoBlobInDB]:
        unique_ids = list(dict.fromkeys(ids))
        if not unique_ids:
            return []
        return await self.delegate.get_by_ids(unique_ids)

    async def add(
        self,
        info_blob: InfoBlobAdd,
        *,
        source_id: UUID | None = None,
        version_state: InfoBlobVersionState = InfoBlobVersionState.ACTIVE,
    ) -> InfoBlobInDB:
        if info_blob.group_id is not None:
            group = await self._get_group(info_blob.group_id)
            assert group is not None
            assert group.embedding_model_id is not None
            embedding_model_id = group.embedding_model_id

        elif info_blob.website_id is not None:
            website = await self._get_website(info_blob.website_id)
            assert website is not None
            embedding_model_id = website.embedding_model_id

        elif info_blob.integration_knowledge_id is not None:
            integration_knowledge = await self._get_integration_knowledge(
                knowledge_id=info_blob.integration_knowledge_id
            )
            assert integration_knowledge is not None
            embedding_model_id = integration_knowledge.embedding_model_id

        else:
            # Skydd mot none
            raise ValueError(
                "InfoBlob must reference a group, website, or integration_knowledge"
            )

        if info_blob.content_hash is None:
            raise ValueError("Published InfoBlob content requires a SHA-256 digest")

        info_blob_to_db = InfoBlobAddToDB(
            **info_blob.model_dump(),
            embedding_model_id=embedding_model_id,
            source_id=source_id or uuid4(),
            version_state=version_state.value,
        )

        record = await self.delegate.add(info_blob_to_db)
        return InfoBlobInDB.model_validate(record)

    async def lock_publication_identity(
        self,
        info_blob: InfoBlobAdd,
        *,
        original_sha256: bytes | None = None,
    ) -> None:
        """Serialize publishers of one identity until the transaction ends.

        Without it two transactions that both find no active version insert
        two. A sync publishes a whole library in one transaction, and an
        advisory lock per document would stay held until it commits and fill
        the shared lock table; an integration knowledge's publications lock its
        row instead, whose lock lives in the tuple and which the sync already
        holds from recording its start.
        """
        if (
            info_blob.group_id is None
            and info_blob.website_id is None
            and info_blob.integration_knowledge_id is not None
        ):
            await self.session.execute(
                sa.select(IntegrationKnowledge.id)
                .where(IntegrationKnowledge.id == info_blob.integration_knowledge_id)
                .with_for_update(key_share=True)
            )
            return
        identities = {
            identity
            for identity in (
                self._publication_identity(info_blob),
                self._original_identity(info_blob, original_sha256),
            )
            if identity is not None
        }
        for identity in sorted(identities):
            await self.session.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {"identity": identity},
            )

    @staticmethod
    def website_publication_identity(website_id: UUID, url: str | None) -> str:
        source_url = normalize_url(url) if url else None
        if source_url is None:
            raise ValueError("Website publications require an HTTP source URL")
        return f"website:{website_id}:url:{source_url}"

    @staticmethod
    def _publication_identity(info_blob: InfoBlobAdd) -> str | None:
        title = info_blob.title if info_blob.title and info_blob.title.strip() else None
        if info_blob.group_id is not None:
            return f"group:{info_blob.group_id}:title:{title}" if title else None
        if info_blob.website_id is not None:
            return InfoBlobRepository.website_publication_identity(
                info_blob.website_id, info_blob.url
            )
        if info_blob.integration_knowledge_id is not None:
            item_id = (
                info_blob.sharepoint_item_id
                if info_blob.sharepoint_item_id and info_blob.sharepoint_item_id.strip()
                else None
            )
            source = item_id or title
            return (
                f"integration:{info_blob.integration_knowledge_id}:source:{source}"
                if source
                else None
            )
        raise ValueError("InfoBlob publication requires a source owner")

    @staticmethod
    def _original_identity(
        info_blob: InfoBlobAdd,
        original_sha256: bytes | None,
    ) -> str | None:
        if info_blob.group_id is None or original_sha256 is None:
            return None
        return f"group:{info_blob.group_id}:original:{original_sha256.hex()}"

    @staticmethod
    def _active_group_upload_identity(
        *,
        group_id: UUID,
        title: str | None,
        original_sha256: bytes | None,
    ) -> ColumnElement[bool]:
        title_identity = sa.and_(
            InfoBlobs.group_id == group_id,
            InfoBlobs.title == title,
        )
        if original_sha256 is None:
            return title_identity
        return sa.or_(
            title_identity,
            sa.and_(
                InfoBlobs.group_id == group_id,
                ObjectContents.sha256 == original_sha256,
            ),
        )

    async def get_active_for_publication(
        self,
        info_blob: InfoBlobAdd,
        *,
        original_sha256: bytes | None = None,
    ) -> InfoBlobPublication | None:
        if self._publication_identity(info_blob) is None:
            return None

        if info_blob.group_id is not None:
            candidate_identity = self._active_group_upload_identity(
                group_id=info_blob.group_id,
                title=info_blob.title,
                original_sha256=original_sha256,
            )
        else:
            source_conditions: list[ColumnElement[bool]] = []
            if info_blob.website_id is not None:
                source_url = normalize_url(info_blob.url) if info_blob.url else None
                assert source_url is not None
                source_conditions.extend(
                    [
                        InfoBlobs.website_id == info_blob.website_id,
                        website_source_url_equals(source_url),
                    ]
                )
            elif info_blob.integration_knowledge_id is not None:
                source_conditions.append(
                    InfoBlobs.integration_knowledge_id
                    == info_blob.integration_knowledge_id
                )
                if (
                    info_blob.sharepoint_item_id is not None
                    and info_blob.sharepoint_item_id.strip()
                ):
                    source_conditions.append(
                        InfoBlobs.sharepoint_item_id == info_blob.sharepoint_item_id
                    )
                else:
                    source_conditions.append(InfoBlobs.title == info_blob.title)
            else:
                raise ValueError("InfoBlob publication requires a source owner")
            candidate_identity = sa.and_(*source_conditions)
        query = sa.select(InfoBlobs)
        if info_blob.group_id is not None and original_sha256 is not None:
            query = query.outerjoin(
                InfoBlobContentReferences,
                InfoBlobContentReferences.info_blob_id == InfoBlobs.id,
            ).outerjoin(
                ObjectContents,
                ObjectContents.id == InfoBlobContentReferences.content_id,
            )

        records = list(
            await self.delegate.get_records_from_query(
                query.where(
                    active_info_blob_version(),
                    candidate_identity,
                )
                .order_by(InfoBlobs.id)
                .limit(2)
                .with_for_update(of=InfoBlobs)
            )
        )
        if len(records) > 1:
            raise InfoBlobPublicationConflictError(
                "Knowledge publication identity is ambiguous"
            )

        record = records[0] if records else None
        if record is None:
            return None
        published = InfoBlobInDB.model_validate(record)
        return InfoBlobPublication(
            info_blob=published,
            original=await self.get_original(published.id),
        )

    async def find_active_upload(
        self,
        *,
        group_id: UUID,
        title: str,
        original_sha256: bytes,
    ) -> ActiveUpload | None:
        rows = (
            await self.session.execute(
                sa.select(
                    InfoBlobs.id,
                    InfoBlobs.embedding_model_id,
                    ObjectContents.sha256,
                )
                .select_from(InfoBlobs)
                .outerjoin(
                    InfoBlobContentReferences,
                    InfoBlobContentReferences.info_blob_id == InfoBlobs.id,
                )
                .outerjoin(
                    ObjectContents,
                    ObjectContents.id == InfoBlobContentReferences.content_id,
                )
                .where(
                    active_info_blob_version(),
                    self._active_group_upload_identity(
                        group_id=group_id,
                        title=title,
                        original_sha256=original_sha256,
                    ),
                )
                .order_by(InfoBlobs.id)
                .limit(2)
            )
        ).all()
        if len(rows) > 1:
            raise InfoBlobPublicationConflictError(
                "Knowledge publication identity is ambiguous"
            )
        if not rows:
            return None
        row = rows[0]
        return ActiveUpload(
            info_blob_id=row.id,
            embedding_model_id=row.embedding_model_id,
            original_sha256=row.sha256,
        )

    async def get_original(self, info_blob_id: UUID) -> InfoBlobOriginal | None:
        row = (
            await self.session.execute(
                sa.select(
                    InfoBlobContentReferences.content_id,
                    InfoBlobContentReferences.original_filename,
                    ObjectContents.tenant_id,
                    ObjectContents.sha256,
                    ObjectContents.access_class,
                    ObjectContents.state,
                )
                .select_from(InfoBlobContentReferences)
                .join(
                    ObjectContents,
                    ObjectContents.id == InfoBlobContentReferences.content_id,
                )
                .where(InfoBlobContentReferences.info_blob_id == info_blob_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return InfoBlobOriginal(
            content_id=row.content_id,
            tenant_id=row.tenant_id,
            sha256=row.sha256,
            access_class=ContentAccessClass(row.access_class),
            state=ContentState(row.state),
            original_filename=row.original_filename,
        )

    async def get_original_availability(self, info_blob_ids: list[UUID]) -> set[UUID]:
        """Return ids with a referenced, available original in one query."""
        if not info_blob_ids:
            return set()
        unique_ids = list(dict.fromkeys(info_blob_ids))
        ids_parameter = sa.bindparam(
            "info_blob_ids",
            type_=ARRAY(PostgreSQLUUID(as_uuid=True)),
        )
        rows = await self.session.scalars(
            sa.select(InfoBlobContentReferences.info_blob_id)
            .join(
                ObjectContents,
                ObjectContents.id == InfoBlobContentReferences.content_id,
            )
            .where(
                InfoBlobContentReferences.info_blob_id == sa.any_(ids_parameter),
                ObjectContents.state == ContentState.AVAILABLE.value,
            ),
            {"info_blob_ids": unique_ids},
        )
        return set(rows)

    async def hydrate_original_availability(
        self, blobs: list[_InfoBlobNoTextT]
    ) -> list[_InfoBlobNoTextT]:
        """Populate the public availability projection in one query.

        Keep this explicit at public read boundaries so internal InfoBlob reads do
        not pay for a join they do not use.
        """
        if not blobs:
            return blobs
        available_ids = await self.get_original_availability(
            [blob.id for blob in blobs]
        )
        for blob in blobs:
            blob.original_available = blob.id in available_ids
        return blobs

    async def add_original_reference(
        self,
        *,
        info_blob_id: UUID,
        content_id: UUID,
        original_filename: str,
    ) -> None:
        await self.session.execute(
            sa.insert(InfoBlobContentReferences).values(
                info_blob_id=info_blob_id,
                content_id=content_id,
                original_filename=original_filename,
            )
        )

    async def replace_original_reference(
        self,
        *,
        info_blob_id: UUID,
        content_id: UUID,
        original_filename: str,
    ) -> None:
        deleted = await self.session.execute(
            sa.delete(InfoBlobContentReferences).where(
                InfoBlobContentReferences.info_blob_id == info_blob_id
            )
        )
        if affected_row_count(deleted) != 1:
            raise RuntimeError("Knowledge original reference changed during repair")
        await self.add_original_reference(
            info_blob_id=info_blob_id,
            content_id=content_id,
            original_filename=original_filename,
        )

    async def refresh_original_filename(
        self,
        *,
        info_blob_id: UUID,
        original_filename: str,
    ) -> None:
        updated = await self.session.execute(
            sa.update(InfoBlobContentReferences)
            .where(InfoBlobContentReferences.info_blob_id == info_blob_id)
            .values(original_filename=original_filename)
        )
        if affected_row_count(updated) != 1:
            raise RuntimeError("Knowledge original reference changed during refresh")

    async def refresh_publication_metadata(
        self,
        info_blob_id: UUID,
        info_blob: InfoBlobAdd,
    ) -> InfoBlobInDB:
        updated_id = await self.session.scalar(
            sa.update(InfoBlobs)
            .where(InfoBlobs.id == info_blob_id, active_info_blob_version())
            .values(
                title=info_blob.title,
                url=info_blob.url,
                website_source_url=(
                    normalize_url(info_blob.url)
                    if info_blob.website_id is not None and info_blob.url
                    else None
                ),
                source_metadata=(
                    [entry.model_dump() for entry in info_blob.source_metadata]
                    if info_blob.source_metadata
                    else None
                ),
            )
            .returning(InfoBlobs.id)
        )
        if updated_id is None:
            raise RuntimeError("The active knowledge version changed during publish")
        refreshed = await self.delegate.get(updated_id)
        if refreshed is None:
            raise RuntimeError("The refreshed knowledge version no longer exists")
        return refreshed

    async def supersede(self, info_blob_id: UUID) -> bool:
        result = await self.session.execute(
            sa.update(InfoBlobs)
            .where(
                InfoBlobs.id == info_blob_id,
                active_info_blob_version(),
            )
            .values(version_state=InfoBlobVersionState.SUPERSEDED.value)
        )
        return affected_row_count(result) == 1

    async def update(self, info_blob: InfoBlobUpdate) -> InfoBlobInDB:
        record = await self.delegate.update(info_blob)
        return InfoBlobInDB.model_validate(record)

    @staticmethod
    def _stored_size() -> ColumnElement[int]:
        """Bytes a version retains: its text, its chunks and its original."""
        chunks_size_subquery = (
            sa.select(sa.func.coalesce(sa.func.sum(InfoBlobChunks.size), 0))
            .where(InfoBlobChunks.info_blob_id == InfoBlobs.id)
            .scalar_subquery()
        )
        original_size_subquery = (
            sa.select(sa.func.coalesce(ObjectContents.size_bytes, 0))
            .select_from(InfoBlobContentReferences)
            .join(
                ObjectContents,
                ObjectContents.id == InfoBlobContentReferences.content_id,
            )
            .where(InfoBlobContentReferences.info_blob_id == InfoBlobs.id)
            .scalar_subquery()
        )
        return sa.func.coalesce(
            chunks_size_subquery
            + sa.func.coalesce(sa.func.octet_length(InfoBlobs.text), 0)
            + sa.func.coalesce(original_size_subquery, 0),
            0,
        )

    async def releasable_search_bytes(
        self, info_blob_ids: Sequence[UUID]
    ) -> dict[UUID, int]:
        """Chunk bytes that replacing these versions releases, per owner."""
        if not info_blob_ids:
            return {}
        rows = await self.session.execute(
            sa.select(InfoBlobs.user_id, sa.func.sum(InfoBlobChunks.size))
            .select_from(InfoBlobs)
            .join(InfoBlobChunks, InfoBlobChunks.info_blob_id == InfoBlobs.id)
            .where(InfoBlobs.id.in_(info_blob_ids))
            .group_by(InfoBlobs.user_id)
        )
        return {user_id: int(size) for user_id, size in rows.tuples()}

    async def release_replaced_search_data(
        self, info_blob_ids: Sequence[UUID]
    ) -> dict[UUID, int]:
        """Delete replaced versions' chunks and shrink their size to match.

        Only the active version of a source is searched, so a replaced version
        needs its text, metadata and original for citations but not its chunks.
        Active and missing versions are left untouched. Parent rows are locked
        before their chunks, the same order as deleting a source family.
        Returns the released bytes per owner.
        """
        if not info_blob_ids:
            return {}
        replaced = (
            await self.session.scalars(
                sa.select(InfoBlobs.id)
                .where(
                    InfoBlobs.id.in_(info_blob_ids),
                    InfoBlobs.version_state == InfoBlobVersionState.SUPERSEDED.value,
                )
                .order_by(InfoBlobs.id)
                .with_for_update()
            )
        ).all()
        if not replaced:
            return {}
        released = await self.releasable_search_bytes(replaced)
        await self.session.execute(
            sa.delete(InfoBlobChunks).where(InfoBlobChunks.info_blob_id.in_(replaced))
        )
        await self.session.execute(
            sa.update(InfoBlobs)
            .where(InfoBlobs.id.in_(replaced))
            .values(size=self._stored_size())
        )
        return released

    async def scan_replaced_page(
        self, *, after: UUID | None, limit: int
    ) -> ReplacedPage:
        """Read the next `limit` versions of any state after `after`, in id order.

        One page reads at most `limit` rows through the primary key, however
        few of them are replaced versions; `versions_read` counts the replaced
        ones and `with_search_data` those of them that still hold chunks.
        """
        replaced = InfoBlobs.version_state == InfoBlobVersionState.SUPERSEDED.value
        holds_chunks = sa.case(
            (
                replaced,
                sa.exists().where(InfoBlobChunks.info_blob_id == InfoBlobs.id),
            ),
            else_=sa.false(),
        )
        rows = (
            await self.session.execute(
                sa.select(InfoBlobs.id, replaced, holds_chunks)
                .where(InfoBlobs.id > after if after is not None else sa.true())
                .order_by(InfoBlobs.id)
                .limit(limit)
            )
        ).all()
        if not rows:
            return ReplacedPage(None, 0, [])
        return ReplacedPage(
            last_id=rows[-1][0],
            versions_read=sum(1 for _, is_replaced, _ in rows if is_replaced),
            with_search_data=[id_ for id_, _, holding in rows if holding],
        )

    async def release_next_replaced_batch(
        self, *, after: UUID | None, limit: int
    ) -> ReplacedBatch:
        """Release the replaced versions in the next page after `after`.

        Versions another transaction holds, for example one deleting their
        source, are skipped rather than waited for.
        """
        page = await self.scan_replaced_page(after=after, limit=limit)
        if page.last_id is None:
            return ReplacedBatch(None, 0, 0, 0, 0)
        if not page.with_search_data:
            return ReplacedBatch(page.last_id, page.versions_read, 0, 0, 0)
        available = (
            await self.session.scalars(
                sa.select(InfoBlobs.id)
                .where(
                    InfoBlobs.id.in_(page.with_search_data),
                    InfoBlobs.version_state == InfoBlobVersionState.SUPERSEDED.value,
                )
                .order_by(InfoBlobs.id)
                .with_for_update(skip_locked=True)
            )
        ).all()
        # Holding the parent locks, recheck which versions still have chunks:
        # a concurrent run may have released some since they were found.
        holding = (
            await self.session.scalars(
                sa.select(InfoBlobChunks.info_blob_id)
                .where(InfoBlobChunks.info_blob_id.in_(available))
                .distinct()
            )
        ).all()
        released = await self.release_replaced_search_data(holding)
        return ReplacedBatch(
            last_scanned_id=page.last_id,
            versions_read=page.versions_read,
            released_versions=len(holding),
            released_bytes=sum(released.values()),
            skipped_busy=len(page.with_search_data) - len(available),
        )

    async def update_size(self, info_blob_id: UUID) -> InfoBlobInDB | None:
        stmt = (
            sa.update(InfoBlobs)
            .values(size=self._stored_size())
            .where(InfoBlobs.id == info_blob_id)
            .returning(InfoBlobs)
        )

        result = await self.delegate.get_model_from_query(stmt)
        info_blob_updated = InfoBlobInDB.model_validate(result)

        return info_blob_updated

    async def get_by_user(self, user_id: UUID):
        query = (
            sa.select(InfoBlobs)
            .where(InfoBlobs.user_id == user_id, active_info_blob_version())
            .order_by(InfoBlobs.created_at)
            .options(selectinload(InfoBlobs.group))
            .options(selectinload(InfoBlobs.embedding_model))
            .options(defer(InfoBlobs.text))
        )
        items = await self.delegate.get_records_from_query(query)
        return [InfoBlobInDBNoText.model_validate(record) for record in items]

    async def get_by_user_and_space(
        self, user_id: UUID, space_ids: list[UUID]
    ) -> list[InfoBlobInDBNoText]:
        """User-scoped info blobs filtered to specific spaces (SQL-level).

        Resolves space membership via group/website/integration_knowledge joins.
        """
        if not space_ids:
            return []

        # Collect parent IDs that belong to the given spaces
        group_ids = list(
            await self.session.scalars(
                sa.select(CollectionsTable.id).where(
                    CollectionsTable.space_id.in_(space_ids)
                )
            )
        )
        website_ids = list(
            await self.session.scalars(
                sa.select(Websites.id).where(Websites.space_id.in_(space_ids))
            )
        )
        integration_ids = list(
            await self.session.scalars(
                sa.select(IntegrationKnowledge.id).where(
                    IntegrationKnowledge.space_id.in_(space_ids)
                )
            )
        )

        space_conditions: list[Any] = []
        if group_ids:
            space_conditions.append(InfoBlobs.group_id.in_(group_ids))
        if website_ids:
            space_conditions.append(InfoBlobs.website_id.in_(website_ids))
        if integration_ids:
            space_conditions.append(
                InfoBlobs.integration_knowledge_id.in_(integration_ids)
            )

        if not space_conditions:
            return []

        query = (
            sa.select(InfoBlobs)
            .where(InfoBlobs.user_id == user_id, active_info_blob_version())
            .where(sa.or_(*space_conditions))
            .order_by(InfoBlobs.created_at)
            .options(selectinload(InfoBlobs.group))
            .options(selectinload(InfoBlobs.embedding_model))
            .options(defer(InfoBlobs.text))
        )
        items = await self.delegate.get_records_from_query(query)
        return [InfoBlobInDBNoText.model_validate(record) for record in items]

    async def get_reference_metadata_by_ids(
        self, info_blob_ids: list[UUID]
    ) -> dict[str, dict[str, object | None]]:
        if not info_blob_ids:
            return {}

        stmt = (
            sa.select(InfoBlobs)
            .where(InfoBlobs.id.in_(info_blob_ids))
            .options(selectinload(InfoBlobs.group))
            .options(selectinload(InfoBlobs.website))
            .options(selectinload(InfoBlobs.integration_knowledge))
        )
        result = await self.session.execute(stmt)

        metadata_by_id: dict[str, dict[str, object | None]] = {}
        for blob in result.scalars():
            source_kind = None
            source_container_name = None
            source_container_id = None
            if blob.group_id is not None:
                source_kind = "collection"
                source_container_id = str(blob.group_id)
                source_container_name = getattr(blob.group, "name", None)
            elif blob.website_id is not None:
                source_kind = "website"
                source_container_id = str(blob.website_id)
                source_container_name = getattr(blob.website, "name", None)
            elif blob.integration_knowledge_id is not None:
                source_kind = "integration_knowledge"
                source_container_id = str(blob.integration_knowledge_id)
                source_container_name = getattr(
                    blob.integration_knowledge, "name", None
                )

            metadata_by_id[str(blob.id)] = {
                "source_title": blob.title,
                "source_url": blob.url,
                "source_kind": source_kind,
                "source_container_kind": source_kind,
                "source_container_name": source_container_name,
                "source_container_id": source_container_id,
            }

        return metadata_by_id

    async def get(self, id: UUID) -> InfoBlobInDB:
        record = await self.delegate.get(id)
        if record is None:
            raise NotFoundException()
        return InfoBlobInDB.model_validate(record)

    async def get_by_title_and_group(
        self, title: str, group_id: UUID
    ) -> InfoBlobInDB | None:
        record = await self.session.scalar(
            sa.select(InfoBlobs).where(
                InfoBlobs.title == title,
                InfoBlobs.group_id == group_id,
                active_info_blob_version(),
            )
        )
        return InfoBlobInDB.model_validate(record) if record is not None else None

    async def list_by_space_ids(
        self,
        *,
        space_ids: list[UUID],
        include_groups: bool,
        include_websites: bool,
        include_integrations: bool,
        limit: int | None = None,
        order_desc: bool = True,
    ) -> list[InfoBlobInDBNoText]:
        if not space_ids:
            return []

        conditions: list[Any] = []

        if include_groups:
            group_ids = await self.session.scalars(
                sa.select(CollectionsTable.id).where(
                    CollectionsTable.space_id.in_(space_ids)
                )
            )
            group_ids_list = list(group_ids)
            if group_ids_list:
                conditions.append(InfoBlobs.group_id.in_(group_ids_list))

        if include_websites:
            website_ids = await self.session.scalars(
                sa.select(Websites.id).where(Websites.space_id.in_(space_ids))
            )
            website_ids_list = list(website_ids)
            if website_ids_list:
                conditions.append(InfoBlobs.website_id.in_(website_ids_list))

        if include_integrations:
            integration_ids = await self.session.scalars(
                sa.select(IntegrationKnowledge.id).where(
                    IntegrationKnowledge.space_id.in_(space_ids)
                )
            )
            integration_ids_list = list(integration_ids)
            if integration_ids_list:
                conditions.append(
                    InfoBlobs.integration_knowledge_id.in_(integration_ids_list)
                )

        if not conditions:
            return []

        query = (
            sa.select(InfoBlobs)
            .where(sa.or_(*conditions), active_info_blob_version())
            .options(selectinload(InfoBlobs.group))
            .options(selectinload(InfoBlobs.embedding_model))
            .options(selectinload(InfoBlobs.website))
            .options(defer(InfoBlobs.text))
        )

        if order_desc:
            query = query.order_by(InfoBlobs.created_at.desc())
        else:
            query = query.order_by(InfoBlobs.created_at.asc())

        if limit is not None:
            query = query.limit(limit)

        records = await self.delegate.get_records_from_query(query)
        return [InfoBlobInDBNoText.model_validate(record) for record in records]

    async def delete_by_sharepoint_item_and_integration_knowledge(
        self,
        sharepoint_item_id: str,
        integration_knowledge_id: UUID,
    ) -> List[InfoBlobInDB]:
        """Delete all info_blobs for a SharePoint item in one integration."""
        stmt = sa.select(InfoBlobs).where(
            sa.and_(
                InfoBlobs.sharepoint_item_id == sharepoint_item_id,
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                active_info_blob_version(),
            )
        )
        result = await self.session.execute(stmt)
        active_blobs = [
            InfoBlobInDB.model_validate(blob) for blob in result.scalars().all()
        ]
        await self.session.execute(
            sa.delete(InfoBlobs).where(
                InfoBlobs.sharepoint_item_id == sharepoint_item_id,
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
            )
        )
        return active_blobs

    async def delete_by_website(self, website_id: UUID):
        await self.delegate.delete_by(conditions={InfoBlobs.website_id: website_id})

    async def delete_by_integration_knowledge(self, integration_knowledge_id: UUID):
        """Delete all info_blobs for a specific integration_knowledge."""
        await self.delegate.delete_by(
            conditions={InfoBlobs.integration_knowledge_id: integration_knowledge_id}
        )

    async def get_by_title_and_integration_knowledge(
        self, title: str, integration_knowledge_id: UUID
    ) -> InfoBlobInDB | None:
        """Get an info_blob by title and integration_knowledge_id."""
        record = await self.session.scalar(
            sa.select(InfoBlobs).where(
                InfoBlobs.title == title,
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                active_info_blob_version(),
            )
        )
        return InfoBlobInDB.model_validate(record) if record is not None else None

    async def refresh_sharepoint_citation(
        self,
        *,
        sharepoint_item_id: str,
        integration_knowledge_id: UUID,
        title: str,
        url: str,
    ) -> bool:
        """Point the active version at the item's current name and address.

        Neither is embedded for a document without source properties, and a
        document with them re-embeds on a rename anyway (its title is in the
        header), so nothing else needs to change. True when a row changed.
        """
        updated = await self.session.execute(
            sa.update(InfoBlobs)
            .where(
                InfoBlobs.sharepoint_item_id == sharepoint_item_id,
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                active_info_blob_version(),
                sa.or_(
                    InfoBlobs.title.is_distinct_from(title),
                    InfoBlobs.url.is_distinct_from(url),
                ),
            )
            .values(title=title, url=url)
            .execution_options(synchronize_session=False)
        )
        return affected_row_count(updated) > 0

    async def get_by_sharepoint_item_and_integration_knowledge(
        self,
        sharepoint_item_id: str,
        integration_knowledge_id: UUID,
    ) -> InfoBlobInDB | None:
        """Get an info_blob by sharepoint_item_id and integration_knowledge_id."""
        record = await self.session.scalar(
            sa.select(InfoBlobs).where(
                InfoBlobs.sharepoint_item_id == sharepoint_item_id,
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                active_info_blob_version(),
            )
        )
        return InfoBlobInDB.model_validate(record) if record is not None else None

    async def get_by_group(self, group_id: UUID) -> list[InfoBlobInDBNoText]:
        records = await self.session.scalars(
            sa.select(InfoBlobs)
            .where(InfoBlobs.group_id == group_id, active_info_blob_version())
            .order_by(InfoBlobs.created_at)
            .options(defer(InfoBlobs.text), selectinload(InfoBlobs.group))
        )
        return [InfoBlobInDBNoText.model_validate(record) for record in records]

    async def get_by_website(
        self,
        website_id: UUID,
    ) -> list[InfoBlobInDBNoText]:
        records = await self.session.scalars(
            sa.select(InfoBlobs)
            .where(
                InfoBlobs.website_id == website_id,
                active_info_blob_version(),
            )
            .order_by(InfoBlobs.id.asc())
            .options(
                defer(InfoBlobs.text),
                selectinload(InfoBlobs.website),
            )
        )
        return [InfoBlobInDBNoText.model_validate(record) for record in records]

    async def get_by_website_page(
        self,
        website_id: UUID,
        *,
        limit: int,
        cursor: UUID | None = None,
        q: str = "",
        prefix: str = "",
    ) -> WebsiteInfoBlobPage:
        conditions = [
            InfoBlobs.website_id == website_id,
            active_info_blob_version(),
        ]
        if q.strip():
            conditions.append(
                _title_or_url_matches(q.strip(), self._website_search_path(prefix))
            )
        if prefix:
            # URL paths are case sensitive; the range compares them byte by byte.
            conditions.append(website_path_below(prefix))
        total_count = await self.session.scalar(
            sa.select(sa.func.count()).select_from(InfoBlobs).where(*conditions)
        )
        query = (
            sa.select(InfoBlobs)
            .where(*conditions)
            .order_by(InfoBlobs.id.asc())
            .options(
                defer(InfoBlobs.text),
                selectinload(InfoBlobs.website),
            )
            .limit(limit + 1)
        )
        if cursor is not None:
            query = query.where(InfoBlobs.id > cursor)

        records = list(await self.session.scalars(query))
        has_more = len(records) > limit
        items = [
            InfoBlobInDBNoText.model_validate(record) for record in records[:limit]
        ]
        return WebsiteInfoBlobPage(
            items=items,
            total_count=total_count or 0,
            next_cursor=items[-1].id if has_more else None,
        )

    @staticmethod
    def _website_search_path(prefix: str) -> ColumnElement[str]:
        """The URL below the selected directory, or below the origin.

        The scheme and host are never searched, so the website's own name does
        not match every resource. Mirrors ``url_anchor`` for integrations.
        """
        url = website_navigation_path()
        if prefix:
            return sa.func.substr(url, len(prefix) + 1)
        return sa.func.regexp_replace(url, r"^https?://[^/]+", "")

    async def get_website_folders(
        self,
        website_id: UUID,
        *,
        prefix: str = "",
        cursor: str | None = None,
        limit: int = 100,
    ) -> WebsiteContentFolderPage:
        """List one level across the entire active index, with bounded output.

        Below a directory, ``ix_info_blobs_active_website_path`` limits the
        grouping to that directory's rows. The website level groups every
        active row of the website, so its cost grows with the website's size,
        not with the page returned.
        """
        url = website_navigation_path()
        conditions = [
            InfoBlobs.website_id == website_id,
            active_info_blob_version(),
            url.op("~")(r"^https?://[^/]+"),
        ]
        if prefix:
            remainder = sa.func.substr(url, len(prefix) + 1)
            conditions.extend(
                [
                    website_path_below(prefix),
                    sa.func.strpos(remainder, "/") > 0,
                    sa.func.split_part(remainder, "/", 1) != "",
                ]
            )
            path = sa.literal(prefix) + sa.func.split_part(remainder, "/", 1) + "/"
            tail = sa.func.substr(remainder, sa.func.strpos(remainder, "/") + 1)
        else:
            origin = sa.func.substring(url, r"^https?://[^/]+")
            path = origin + "/"
            tail = sa.func.substr(url, sa.func.length(origin) + 2)

        groups = (
            sa.select(
                path.label("path"),
                sa.func.count().label("item_count"),
                sa.func.bool_or(sa.func.strpos(tail, "/") > 1).label("has_children"),
            )
            .where(*conditions)
            .group_by(path)
            .subquery()
        )
        query = sa.select(groups).order_by(groups.c.path).limit(limit + 1)
        if cursor is not None:
            query = query.where(groups.c.path > cursor)
        rows = (await self.session.execute(query)).all()
        items = [
            WebsiteContentFolder(
                path=row.path, count=row.item_count, has_children=row.has_children
            )
            for row in rows[:limit]
        ]
        return WebsiteContentFolderPage(
            items=items,
            next_cursor=items[-1].path if len(rows) > limit else None,
        )

    @staticmethod
    def _source_filter(
        group_ids: list[UUID],
        website_ids: list[UUID],
        integration_knowledge_ids: list[UUID],
    ) -> ColumnElement[bool]:
        return sa.or_(
            InfoBlobs.group_id.in_(group_ids),
            InfoBlobs.website_id.in_(website_ids),
            InfoBlobs.integration_knowledge_id.in_(integration_knowledge_ids),
        )

    async def count_by_sources(
        self,
        *,
        group_ids: list[UUID],
        website_ids: list[UUID],
        integration_knowledge_ids: list[UUID],
    ) -> int:
        stmt = sa.select(sa.func.count()).where(
            self._source_filter(group_ids, website_ids, integration_knowledge_ids),
            active_info_blob_version(),
        )
        return await self.session.scalar(stmt) or 0

    async def list_by_sources(
        self,
        *,
        group_ids: list[UUID],
        website_ids: list[UUID],
        integration_knowledge_ids: list[UUID],
        limit: int,
        offset: int = 0,
    ) -> list[InfoBlobListing]:
        """Document identities across the given sources, alphabetically.

        Ordered on the displayed label rather than ``created_at`` because the
        result is read by a human (via the model) as a table of contents; ``id``
        breaks ties so paging by ``offset`` stays stable.
        """
        label = sa.func.coalesce(InfoBlobs.title, InfoBlobs.url)
        stmt = (
            sa.select(InfoBlobs.id, InfoBlobs.title, InfoBlobs.url)
            .where(
                self._source_filter(group_ids, website_ids, integration_knowledge_ids),
                active_info_blob_version(),
            )
            .order_by(label.nulls_last(), InfoBlobs.id)
            .limit(limit)
            .offset(offset)
        )
        rows = await self.session.execute(stmt)
        return [
            InfoBlobListing(id=row.id, title=row.title, url=row.url)
            for row in rows.all()
        ]

    async def delete(self, id: UUID) -> InfoBlobInDB:
        source_id = await self.session.scalar(
            sa.select(InfoBlobs.source_id).where(InfoBlobs.id == id)
        )
        if source_id is None:
            raise ValueError(f"InfoBlob {id} does not exist")
        active = await self.delegate.get_record_from_query(
            sa.select(InfoBlobs).where(
                InfoBlobs.source_id == source_id,
                active_info_blob_version(),
            )
        )
        if active is None:
            raise ValueError(f"InfoBlob source {source_id} has no active version")
        deleted = InfoBlobInDB.model_validate(active)
        await self.session.execute(
            sa.delete(InfoBlobs).where(InfoBlobs.source_id == source_id)
        )
        return deleted

    async def get_count_of_group(self, group_id: UUID):
        stmt = (
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(InfoBlobs.group_id == group_id, active_info_blob_version())
        )

        return await self.session.scalar(stmt)

    async def get_count_by_integration_knowledge(self, integration_knowledge_id: UUID):
        """Get the count of info_blobs associated with a specific integration_knowledge."""
        stmt = (
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                active_info_blob_version(),
            )
        )

        return await self.session.scalar(stmt)

    async def get_integration_knowledge_page(
        self,
        integration_knowledge_id: UUID,
        *,
        q: str | None = None,
        url_anchor: str | None = None,
        sort: IntegrationDocumentSort = "path",
        descending: bool = False,
        limit: int,
        offset: int = 0,
    ) -> IntegrationDocumentsPage:
        """Active documents of one item, filtered on title, path or a property
        value, as one page.

        ``url_anchor`` is the item's own URL without a trailing slash; the
        search covers the URL part after it.
        """
        conditions: list[ColumnElement[bool]] = [
            InfoBlobs.integration_knowledge_id == integration_knowledge_id,
            active_info_blob_version(),
        ]
        if q:
            conditions.append(_document_matches(q, url_anchor))
        totals = (
            await self.session.execute(
                sa.select(
                    sa.func.count(), sa.func.coalesce(sa.func.sum(InfoBlobs.size), 0)
                )
                .select_from(InfoBlobs)
                .where(*conditions)
            )
        ).one()
        ordering = [
            (key.desc() if descending else key.asc()).nulls_last()
            for key in _document_sort_keys(sort)
        ]
        query = (
            sa.select(InfoBlobs)
            .where(*conditions)
            .order_by(*ordering, InfoBlobs.id.asc())
            .options(defer(InfoBlobs.text))
            .limit(limit)
            .offset(offset)
        )
        records = await self.session.scalars(query)
        return IntegrationDocumentsPage(
            items=[InfoBlobInDBNoText.model_validate(record) for record in records],
            total_count=int(totals[0] or 0),
            total_size=int(totals[1] or 0),
        )

    async def get_by_filter_integration_knowledge(
        self, integration_knowledge_id: UUID
    ) -> list[InfoBlobInDB]:
        """Get all info_blobs for a specific integration_knowledge."""
        query = (
            sa.select(InfoBlobs)
            .where(
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                active_info_blob_version(),
            )
            .options(selectinload(InfoBlobs.embedding_model))
        )
        records = await self.delegate.get_models_from_query(query)
        return [InfoBlobInDB.model_validate(record) for record in records]

    async def get_sharepoint_item_ids_for_integration_knowledge(
        self, integration_knowledge_id: UUID
    ) -> list[tuple[UUID, str]]:
        """Return (blob_id, sharepoint_item_id) for SharePoint-backed blobs.

        Lightweight (two columns, no text) — used by full-sync reconciliation to
        diff the indexed set against what still exists in SharePoint.
        """
        stmt = sa.select(InfoBlobs.id, InfoBlobs.sharepoint_item_id).where(
            sa.and_(
                InfoBlobs.integration_knowledge_id == integration_knowledge_id,
                InfoBlobs.sharepoint_item_id.is_not(None),
                active_info_blob_version(),
            )
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    def _sum_stmt(self):
        return (
            sa.select(sa.func.sum(InfoBlobs.size))
            .select_from(InfoBlobs)
            .where(active_info_blob_version())
        )

    @staticmethod
    def retained_size_of_user_stmt(user_id: UUID):
        return sa.select(sa.func.sum(InfoBlobs.size)).where(
            InfoBlobs.user_id == user_id
        )

    @staticmethod
    def retained_size_of_tenant_stmt(tenant_id: UUID):
        return (
            sa.select(sa.func.sum(InfoBlobs.size))
            .select_from(InfoBlobs)
            .join(Users)
            .where(Users.tenant_id == tenant_id)
        )

    async def get_total_size_of_group(self, group_id: UUID):
        stmt = self._sum_stmt().where(InfoBlobs.group_id == group_id)

        size = await self.session.scalar(stmt)

        if size is None:
            return 0

        return size

    async def get_total_size_of_integration_knowledge(
        self, integration_knowledge_id: UUID
    ) -> int:
        size = await self.session.scalar(
            self._sum_stmt().where(
                InfoBlobs.integration_knowledge_id == integration_knowledge_id
            )
        )
        return size or 0

    async def get_total_size_of_user(self, user_id: UUID):
        stmt = self._sum_stmt().where(InfoBlobs.user_id == user_id)

        size = await self.session.scalar(stmt)

        if size is None:
            return 0

        return size

    async def get_retained_size_of_user(self, user_id: UUID) -> int:
        size = await self.session.scalar(self.retained_size_of_user_stmt(user_id))
        return size or 0

    async def get_total_size_of_tenant(self, tenant_id: UUID):
        stmt = self._sum_stmt().join(Users).where(Users.tenant_id == tenant_id)

        size = await self.session.scalar(stmt)

        if size is None:
            return 0

        return size

    async def get_retained_size_of_tenant(self, tenant_id: UUID) -> int:
        size = await self.session.scalar(self.retained_size_of_tenant_stmt(tenant_id))
        return size or 0

    async def get_ids(self):
        stmt = sa.select(InfoBlobs.id).where(active_info_blob_version())

        ids = await self.session.scalars(stmt)

        return set(ids)

    async def batch_delete_by_source_urls_and_website(
        self, urls: list[str], website_id: UUID
    ) -> int:
        """Remove observed absent sources without touching namesakes or unknown URLs."""
        if not urls:
            return 0

        active_count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(
                InfoBlobs.website_id == website_id,
                InfoBlobs.website_source_url.in_(urls),
                active_info_blob_version(),
            )
        )
        stmt = sa.delete(InfoBlobs).where(
            InfoBlobs.website_id == website_id, InfoBlobs.website_source_url.in_(urls)
        )
        await self.session.execute(stmt)
        return active_count or 0
