from enum import Enum
from typing import TYPE_CHECKING, Optional, Union

from intric.base.base_entity import Entity
from intric.embedding_models.domain.embedding_model import EmbeddingModel
from intric.main.models import NOT_PROVIDED, NotProvided
from intric.websites.domain.crawl_run import CrawlRun, CrawlType
from intric.authentication.encryption import encrypt_password, decrypt_password

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.database.tables.websites_table import Websites as WebsitesTable
    from intric.users.user import UserInDB


class UpdateInterval(str, Enum):
    NEVER = "never"
    DAILY = "daily"
    EVERY_3_DAYS = "every_3_days"
    WEEKLY = "weekly"
    EVERY_2_WEEKS = "every_2_weeks"
    MONTHLY = "monthly"


class Website(Entity):
    def __init__(
        self,
        id: Optional["UUID"],
        created_at: Optional["datetime"],
        updated_at: Optional["datetime"],
        space_id: "UUID",
        user_id: "UUID",
        tenant_id: "UUID",
        url: str,
        name: Optional[str],
        download_files: bool,
        crawl_type: CrawlType,
        update_interval: UpdateInterval,
        embedding_model: "EmbeddingModel",
        size: int,
        latest_crawl: Optional["CrawlRun"],
        requires_auth: bool = False,
        auth_username: Optional[str] = None,
        auth_password: Optional[str] = None,  # Plain text, will be encrypted
        auth_last_verified: Optional["datetime"] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.space_id = space_id
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.url = url
        self.name = name
        self.download_files = download_files
        self.crawl_type = crawl_type
        self.update_interval = update_interval
        self.embedding_model = embedding_model
        self.size = size
        self.latest_crawl = latest_crawl
        self.requires_auth = requires_auth
        self.auth_username = auth_username
        self.auth_password = auth_password  # Store plain text in domain object
        self.auth_last_verified = auth_last_verified

    @classmethod
    def create(
        cls,
        space_id: "UUID",
        user: "UserInDB",
        url: str,
        name: Optional[str],
        download_files: bool,
        crawl_type: CrawlType,
        update_interval: UpdateInterval,
        embedding_model: "EmbeddingModel",
        requires_auth: bool = False,
        auth_username: Optional[str] = None,
        auth_password: Optional[str] = None,
    ) -> "Website":
        return cls(
            id=None,
            created_at=None,
            updated_at=None,
            space_id=space_id,
            user_id=user.id,
            tenant_id=user.tenant_id,
            url=url,
            name=name,
            download_files=download_files,
            crawl_type=crawl_type,
            update_interval=update_interval,
            embedding_model=embedding_model,
            size=0,
            latest_crawl=None,
            requires_auth=requires_auth,
            auth_username=auth_username,
            auth_password=auth_password,
            auth_last_verified=None,
        )

    @classmethod
    def to_domain(
        cls,
        record: "WebsitesTable",
        embedding_model: "EmbeddingModel",
    ) -> "Website":
        # Decrypt password if present
        auth_password = None
        if hasattr(record, 'encrypted_auth_password') and record.encrypted_auth_password:
            auth_password = decrypt_password(record.encrypted_auth_password)
        
        return cls(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            space_id=record.space_id,
            user_id=record.user_id,
            tenant_id=record.tenant_id,
            url=record.url,
            name=record.name,
            download_files=record.download_files,
            crawl_type=record.crawl_type,
            update_interval=record.update_interval,
            embedding_model=embedding_model,
            size=record.size,
            latest_crawl=CrawlRun.to_domain(record.latest_crawl) if record.latest_crawl else None,
            requires_auth=getattr(record, 'requires_auth', False),
            auth_username=getattr(record, 'auth_username', None),
            auth_password=auth_password,
            auth_last_verified=getattr(record, 'auth_last_verified', None),
        )

    def update(
        self,
        url: Union[str, NotProvided] = NOT_PROVIDED,
        name: Union[str, NotProvided] = NOT_PROVIDED,
        download_files: Union[bool, NotProvided] = NOT_PROVIDED,
        crawl_type: Union[CrawlType, NotProvided] = NOT_PROVIDED,
        update_interval: Union[UpdateInterval, NotProvided] = NOT_PROVIDED,
        requires_auth: Union[bool, NotProvided] = NOT_PROVIDED,
        auth_username: Union[Optional[str], NotProvided] = NOT_PROVIDED,
        auth_password: Union[Optional[str], NotProvided] = NOT_PROVIDED,
    ) -> "Website":
        if url is not NOT_PROVIDED:
            self.url = url
        if name is not NOT_PROVIDED:
            self.name = name
        if download_files is not NOT_PROVIDED:
            self.download_files = download_files
        if crawl_type is not NOT_PROVIDED:
            self.crawl_type = crawl_type
        if update_interval is not NOT_PROVIDED:
            self.update_interval = update_interval
        if requires_auth is not NOT_PROVIDED:
            self.requires_auth = requires_auth
        if auth_username is not NOT_PROVIDED:
            self.auth_username = auth_username
        if auth_password is not NOT_PROVIDED:
            self.auth_password = auth_password

        return self

    def get_encrypted_password(self) -> Optional[str]:
        """Get encrypted password for database storage."""
        if self.auth_password:
            return encrypt_password(self.auth_password)
        return None


class WebsiteSparse(Entity):
    """
    A sparse representation of a website.
    """

    def __init__(
        self,
        id: "UUID",
        created_at: "datetime",
        updated_at: "datetime",
        user_id: "UUID",
        tenant_id: "UUID",
        embedding_model_id: "UUID",
        space_id: "UUID",
        name: str,
        url: str,
        download_files: bool,
        crawl_type: CrawlType,
        update_interval: UpdateInterval,
        size: int,
        requires_auth: bool = False,
        auth_username: Optional[str] = None,
        encrypted_auth_password: Optional[str] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.embedding_model_id = embedding_model_id
        self.space_id = space_id
        self.name = name
        self.url = url
        self.download_files = download_files
        self.crawl_type = crawl_type
        self.update_interval = update_interval
        self.size = size
        self.requires_auth = requires_auth
        self.auth_username = auth_username
        self.encrypted_auth_password = encrypted_auth_password

    @classmethod
    def to_domain(cls, record: "WebsitesTable") -> "WebsiteSparse":
        return cls(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            user_id=record.user_id,
            tenant_id=record.tenant_id,
            embedding_model_id=record.embedding_model_id,
            space_id=record.space_id,
            name=record.name,
            url=record.url,
            download_files=record.download_files,
            crawl_type=record.crawl_type,
            update_interval=record.update_interval,
            size=record.size,
            requires_auth=getattr(record, 'requires_auth', False),
            auth_username=getattr(record, 'auth_username', None),
            encrypted_auth_password=getattr(record, 'encrypted_auth_password', None),
        )
