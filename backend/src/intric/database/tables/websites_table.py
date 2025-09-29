from typing import Optional
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, and_, select, Enum
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.base_class import BasePublic
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.job_table import Jobs
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.crawler_engine import CrawlerEngine


class CrawlRuns(BasePublic):
    pages_crawled: Mapped[Optional[int]] = mapped_column()
    files_downloaded: Mapped[Optional[int]] = mapped_column()
    pages_failed: Mapped[Optional[int]] = mapped_column()
    files_failed: Mapped[Optional[int]] = mapped_column()

    # Foreign keys
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    website_id: Mapped[UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"))
    job_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey(Jobs.id, ondelete="SET NULL"))

    # Relationships
    job: Mapped[Jobs] = relationship()


class Websites(BasePublic):
    name: Mapped[Optional[str]] = mapped_column()
    url: Mapped[str] = mapped_column()
    download_files: Mapped[bool] = mapped_column()
    crawl_type: Mapped[CrawlType] = mapped_column()
    update_interval: Mapped[str] = mapped_column()
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    crawler_engine: Mapped[CrawlerEngine] = mapped_column(
        Enum(CrawlerEngine, name="crawlerengine", create_constraint=True)
    )

    # Foreign keys
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    embedding_model_id: Mapped[UUID] = mapped_column(ForeignKey(EmbeddingModels.id))
    group_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CollectionsTable.id, ondelete="SET NULL")
    )
    space_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey(Spaces.id, ondelete="CASCADE"))

    # Relationships
    group: Mapped[CollectionsTable] = relationship()
    embedding_model: Mapped[EmbeddingModels] = relationship()

    @declared_attr
    def __mapper_args__(cls):
        most_recent_crawl = (
            select(CrawlRuns.id)
            .where(CrawlRuns.website_id == cls.id)
            .order_by(CrawlRuns.created_at.desc())
            .limit(1)
            .correlate(cls.__table__)
            .scalar_subquery()
        )

        latest_crawl_relationship = relationship(
            CrawlRuns,
            primaryjoin=and_(CrawlRuns.id == most_recent_crawl, CrawlRuns.website_id == cls.id),
            uselist=False,
            viewonly=True,
        )
        return {"properties": {"latest_crawl": latest_crawl_relationship}}
