from enum import Enum
from typing import TYPE_CHECKING, Optional, Union, cast, overload

from typing_extensions import override

from intric.base.base_entity import Entity
from intric.embedding_models.domain.embedding_model import EmbeddingModel
from intric.main.models import NOT_PROVIDED, NotProvided, is_provided
from intric.websites.domain.crawl_run import CrawlRun, CrawlType
from intric.websites.domain.http_auth_credentials import HttpAuthCredentials

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.database.tables.websites_table import (
        CrawlRuns as CrawlRunsTable,
    )
    from intric.database.tables.websites_table import (
        Websites as WebsitesTable,
    )
    from intric.users.user import UserInDB


class UpdateInterval(str, Enum):
    """Defines how frequently a website should be crawled.

    Why: Provides flexible scheduling options for automated crawling.
    """

    NEVER = "never"
    DAILY = "daily"  # Crawl every day at 1:00 UTC (2 AM Swedish winter / 3 AM summer)
    EVERY_OTHER_DAY = "every_other_day"  # Crawl every 2 days at 1:00 UTC (2 AM Swedish winter / 3 AM summer)
    WEEKLY = (
        "weekly"  # Crawl every Friday at 1:00 UTC (2 AM Swedish winter / 3 AM summer)
    )


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
        last_crawled_at: Optional["datetime"] = None,
        http_auth: Optional[HttpAuthCredentials] = None,
        consecutive_failures: int = 0,
        next_retry_at: Optional["datetime"] = None,
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
        self.last_crawled_at = last_crawled_at
        self.http_auth = http_auth
        self.consecutive_failures = consecutive_failures
        self.next_retry_at = next_retry_at

    @property
    def requires_auth(self) -> bool:
        """Domain rule: Website requires auth if credentials are present."""
        return self.http_auth is not None

    @property
    def is_auto_disabled(self) -> bool:
        """Domain rule: Website is auto-disabled if circuit breaker triggered.

        Why: Distinguishes user-set NEVER from system auto-disable after failures.
        """
        return (
            self.update_interval == UpdateInterval.NEVER
            and self.consecutive_failures >= 10
        )

    def set_http_auth(self, username: str, password: str) -> "Website":
        """Set HTTP auth credentials for this website.

        Why: Domain method enforces business rules and uses value object.

        Args:
            username: HTTP Basic Auth username
            password: HTTP Basic Auth password

        Returns:
            self for method chaining

        Raises:
            ValueError: If credentials are invalid
        """
        self.http_auth = HttpAuthCredentials.from_website_url(
            username=username, password=password, website_url=self.url
        )
        return self

    def remove_http_auth(self) -> "Website":
        """Remove HTTP auth credentials from this website.

        Why: Explicit domain operation for auth removal.

        Returns:
            self for method chaining
        """
        self.http_auth = None
        return self

    @overload
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
        http_auth_username: Optional[str] = None,
        http_auth_password: Optional[str] = None,
        /,
    ) -> "Website": ...

    @overload
    @classmethod
    def create(
        cls,
        *,
        space_id: "UUID",
        user: "UserInDB",
        url: str,
        name: Optional[str],
        download_files: bool,
        crawl_type: CrawlType,
        update_interval: UpdateInterval,
        embedding_model: "EmbeddingModel",
        http_auth_username: Optional[str] = None,
        http_auth_password: Optional[str] = None,
    ) -> "Website": ...

    @override
    @classmethod
    def create(cls, *args: object, **kwargs: object) -> "Website":
        if args:
            (
                space_id,
                user,
                url,
                name,
                download_files,
                crawl_type,
                update_interval,
                embedding_model,
                *optional_auth,
            ) = args
            http_auth_username = cast(
                Optional[str], optional_auth[0] if optional_auth else None
            )
            http_auth_password = cast(
                Optional[str], optional_auth[1] if len(optional_auth) > 1 else None
            )
        else:
            space_id = kwargs["space_id"]
            user = kwargs["user"]
            url = kwargs["url"]
            name = kwargs.get("name")
            download_files = kwargs["download_files"]
            crawl_type = kwargs["crawl_type"]
            update_interval = kwargs["update_interval"]
            embedding_model = kwargs["embedding_model"]
            http_auth_username = kwargs.get("http_auth_username")
            http_auth_password = kwargs.get("http_auth_password")

        space_id = cast("UUID", space_id)
        user = cast("UserInDB", user)
        url = cast(str, url)
        name = cast(Optional[str], name)
        download_files = cast(bool, download_files)
        crawl_type = cast(CrawlType, crawl_type)
        update_interval = cast(UpdateInterval, update_interval)
        embedding_model = cast("EmbeddingModel", embedding_model)
        http_auth_username = cast(Optional[str], http_auth_username)
        http_auth_password = cast(Optional[str], http_auth_password)

        website = cls(
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
            last_crawled_at=None,
            http_auth=None,
        )

        # Set auth if both username and password provided
        if http_auth_username and http_auth_password:
            website.set_http_auth(http_auth_username, http_auth_password)

        return website

    @classmethod
    @overload
    def to_domain(
        cls,
        db_model: "WebsitesTable",
        *,
        embedding_model: "EmbeddingModel",
        http_auth: Optional[HttpAuthCredentials] = None,
    ) -> "Website": ...

    @overload
    @classmethod
    def to_domain(
        cls,
        *,
        record: "WebsitesTable",
        embedding_model: "EmbeddingModel",
        http_auth: Optional[HttpAuthCredentials] = None,
    ) -> "Website": ...

    @override
    @classmethod
    def to_domain(
        cls,
        db_model: object = None,
        *args: object,
        **kwargs: object,
    ) -> "Website":
        del args
        record = cast(
            "WebsitesTable",
            db_model if db_model is not None else kwargs["record"],
        )
        embedding_model = cast("EmbeddingModel", kwargs["embedding_model"])
        http_auth = cast(Optional[HttpAuthCredentials], kwargs.get("http_auth"))
        latest_crawl = cast(
            "CrawlRunsTable | None", getattr(record, "latest_crawl", None)
        )

        return cls(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            space_id=cast(
                "UUID", record.space_id
            ),  # DB invariant: space_id is non-null for persisted websites
            user_id=record.user_id,
            tenant_id=record.tenant_id,
            url=record.url,
            name=record.name,
            download_files=record.download_files,
            crawl_type=record.crawl_type,
            update_interval=UpdateInterval(record.update_interval),
            embedding_model=embedding_model,
            size=record.size,
            latest_crawl=CrawlRun.to_domain(db_model=latest_crawl)
            if latest_crawl
            else None,
            last_crawled_at=record.last_crawled_at,
            http_auth=http_auth,
            consecutive_failures=record.consecutive_failures,
            next_retry_at=record.next_retry_at,
        )

    def update(
        self,
        url: Union[str, NotProvided] = NOT_PROVIDED,
        name: Union[str, None, NotProvided] = NOT_PROVIDED,
        download_files: Union[bool, NotProvided] = NOT_PROVIDED,
        crawl_type: Union[CrawlType, NotProvided] = NOT_PROVIDED,
        update_interval: Union[UpdateInterval, NotProvided] = NOT_PROVIDED,
        http_auth_username: Union[str, None, NotProvided] = NOT_PROVIDED,
        http_auth_password: Union[str, None, NotProvided] = NOT_PROVIDED,
    ) -> "Website":
        if is_provided(url):
            self.url = url
        if is_provided(name):
            self.name = name
        if is_provided(download_files):
            self.download_files = download_files
        if is_provided(crawl_type):
            self.crawl_type = crawl_type
        if is_provided(update_interval):
            self.update_interval = update_interval
            # Reset circuit breaker when user manually changes schedule
            # Why: User action indicates intent to retry, regardless of past failures
            if self.consecutive_failures >= 10:
                self.consecutive_failures = 0
                self.next_retry_at = None

        # Handle auth updates (both must be provided together or both None)
        if is_provided(http_auth_username) or is_provided(http_auth_password):
            # If either is explicitly None, remove auth
            if http_auth_username is None or http_auth_password is None:
                self.remove_http_auth()
            # If both provided, set/update auth
            elif is_provided(http_auth_username) and is_provided(http_auth_password):
                self.set_http_auth(http_auth_username, http_auth_password)
            # If only one provided, that's an error
            else:
                raise ValueError(
                    "Both http_auth_username and http_auth_password must be provided together"
                )

        return self

    def update_last_crawled_at(self, timestamp: "datetime") -> "Website":
        """Update when this website was last crawled.

        Why: Domain method ensures changes go through proper entity lifecycle.
        """
        self.last_crawled_at = timestamp
        return self


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
        last_crawled_at: Optional["datetime"],
        consecutive_failures: int = 0,
        next_retry_at: Optional["datetime"] = None,
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
        self.last_crawled_at = last_crawled_at
        self.consecutive_failures = consecutive_failures
        self.next_retry_at = next_retry_at

    @classmethod
    @overload
    def to_domain(cls, db_model: "WebsitesTable") -> "WebsiteSparse": ...

    @overload
    @classmethod
    def to_domain(
        cls,
        *,
        record: "WebsitesTable",
    ) -> "WebsiteSparse": ...

    @override
    @classmethod
    def to_domain(
        cls,
        db_model: object = None,
        *args: object,
        **kwargs: object,
    ) -> "WebsiteSparse":
        del args
        record = cast(
            "WebsitesTable",
            db_model if db_model is not None else kwargs["record"],
        )

        return cls(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            user_id=record.user_id,
            tenant_id=record.tenant_id,
            embedding_model_id=record.embedding_model_id,
            space_id=cast(
                "UUID", record.space_id
            ),  # DB invariant: space_id is non-null for persisted websites
            name=cast(
                str, record.name
            ),  # DB invariant: name is non-null for sparse website records
            url=record.url,
            download_files=record.download_files,
            crawl_type=record.crawl_type,
            update_interval=UpdateInterval(record.update_interval),
            size=record.size,
            last_crawled_at=record.last_crawled_at,
            consecutive_failures=record.consecutive_failures,
            next_retry_at=record.next_retry_at,
        )
