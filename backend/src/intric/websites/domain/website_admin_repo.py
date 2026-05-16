from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from intric.audit.infrastructure.audit_log_repo_impl import escape_like
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.websites.domain.crawl_circuit_reset import (
    CrawlCircuitResetNotFound,
    CrawlCircuitResetPreviousState,
    CrawlCircuitResetResult,
    CrawlCircuitResetSucceeded,
    CrawlCircuitResetWebsite,
)
from intric.websites.domain.crawl_interval_change import (
    CrawlIntervalChangeApplied,
    CrawlIntervalChangeNotFound,
    CrawlIntervalChangeResult,
    CrawlIntervalChangeUnchanged,
    CrawlIntervalChangeWebsite,
)
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.crawler_failure_inventory import (
    CrawlerFailureInventory,
    CrawlerFailureInventoryItem,
    CrawlerFailureState,
)
from intric.websites.domain.crawler_scheduled_aggregate import (
    CrawlerScheduledAggregate,
    CrawlerScheduledIntervalBucket,
)
from intric.websites.domain.crawler_tenant_website_inventory import (
    CrawlerTenantWebsiteInventory,
    CrawlerTenantWebsiteInventoryItem,
    CrawlerTenantWebsiteInventorySort,
)
from intric.websites.domain.website import (
    WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    UpdateInterval,
)

if TYPE_CHECKING:
    from intric.database.database import AsyncSession


def _website_failure_state_case():
    """Return the labeled SQL CASE that classifies a website's failure state.

    Two callers share this: the failure inventory (only rows where the CASE
    isn't NULL) and the tenant website inventory (every row, NULL meaning
    healthy). Extracting it keeps the AUTO_DISABLED / BACKED_OFF heuristics
    in one place — if the threshold or condition shifts, both endpoints
    pick up the change without a separate edit.

    Return type is left to inference because `sa.case().label()` produces
    a Labeled[Case[str]] which is not a stable public name in SQLAlchemy
    2.0 stubs; an explicit annotation would force a `reportUnknown*`
    pyright error without adding caller-visible safety. Callers treat
    the result as an opaque labeled column expression.
    """
    auto_disabled_condition = sa.and_(
        WebsitesTable.update_interval == UpdateInterval.NEVER,
        WebsitesTable.consecutive_failures >= WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    )
    backed_off_condition = sa.and_(
        WebsitesTable.consecutive_failures > 0,
        WebsitesTable.next_retry_at.is_not(None),
        WebsitesTable.update_interval != UpdateInterval.NEVER,
    )
    return sa.case(
        (auto_disabled_condition, CrawlerFailureState.AUTO_DISABLED.value),
        (backed_off_condition, CrawlerFailureState.BACKED_OFF.value),
    ).label("failure_state")


class WebsiteAdminRepository:
    def __init__(self, session: "AsyncSession"):
        self.session = session

    async def crawler_failure_inventory(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
        state_filter: CrawlerFailureState | None = None,
    ) -> CrawlerFailureInventory:
        return await self._crawler_failure_inventory(
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
            state_filter=state_filter,
        )

    async def crawler_failure_inventory_for_tenant(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID,
        state_filter: CrawlerFailureState | None = None,
    ) -> CrawlerFailureInventory:
        return await self._crawler_failure_inventory(
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
            state_filter=state_filter,
        )

    async def _crawler_failure_inventory(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
        state_filter: CrawlerFailureState | None = None,
    ) -> CrawlerFailureInventory:
        auto_disabled_condition = sa.and_(
            WebsitesTable.update_interval == UpdateInterval.NEVER,
            WebsitesTable.consecutive_failures
            >= WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
        )
        backed_off_condition = sa.and_(
            WebsitesTable.consecutive_failures > 0,
            WebsitesTable.next_retry_at.is_not(None),
            WebsitesTable.update_interval != UpdateInterval.NEVER,
        )
        failure_state = _website_failure_state_case()

        # The state_filter narrows the failure-state predicate to exactly one
        # bucket; without it the inventory returns both buckets so the admin
        # page's existing default view continues to work unchanged.
        if state_filter is CrawlerFailureState.AUTO_DISABLED:
            failure_conditions = [auto_disabled_condition]
        elif state_filter is CrawlerFailureState.BACKED_OFF:
            failure_conditions = [backed_off_condition]
        else:
            failure_conditions = [sa.or_(auto_disabled_condition, backed_off_condition)]
        if tenant_id is not None:
            failure_conditions.append(WebsitesTable.tenant_id == tenant_id)

        total_stmt = (
            sa.select(sa.func.count(WebsitesTable.id))
            .select_from(WebsitesTable)
            .where(*failure_conditions)
        )
        total = int(await self.session.scalar(total_stmt) or 0)

        rows_from = sa.outerjoin(
            WebsitesTable,
            Tenants,
            WebsitesTable.tenant_id == Tenants.id,
        )
        rows_stmt = (
            sa.select(
                WebsitesTable.id.label("website_id"),
                WebsitesTable.url.label("website_url"),
                WebsitesTable.name.label("website_name"),
                WebsitesTable.tenant_id.label("tenant_id"),
                Tenants.display_name.label("tenant_display_name"),
                failure_state,
                WebsitesTable.update_interval.label("update_interval"),
                WebsitesTable.consecutive_failures.label("consecutive_failures"),
                WebsitesTable.next_retry_at.label("next_retry_at"),
                WebsitesTable.last_crawled_at.label("last_crawled_at"),
                WebsitesTable.updated_at.label("updated_at"),
            )
            .select_from(rows_from)
            .where(*failure_conditions)
            .order_by(
                WebsitesTable.consecutive_failures.desc(),
                WebsitesTable.updated_at.desc(),
                WebsitesTable.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(rows_stmt)
        items: list[CrawlerFailureInventoryItem] = []
        for row in result.mappings():
            update_interval = UpdateInterval(str(row["update_interval"]))
            consecutive_failures = int(row["consecutive_failures"])
            failure_state_value = row["failure_state"]
            if failure_state_value is None:
                raise RuntimeError("Crawler failure inventory row has no failure state")
            items.append(
                CrawlerFailureInventoryItem(
                    website_id=row["website_id"],
                    website_url=str(row["website_url"]),
                    website_name=row["website_name"],
                    tenant_id=row["tenant_id"],
                    tenant_display_name=row["tenant_display_name"],
                    state=CrawlerFailureState(str(failure_state_value)),
                    update_interval=update_interval,
                    consecutive_failures=consecutive_failures,
                    next_retry_at=row["next_retry_at"],
                    last_crawled_at=row["last_crawled_at"],
                    updated_at=row["updated_at"],
                )
            )

        return CrawlerFailureInventory(
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def tenant_website_inventory(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        offset: int,
        search: str | None = None,
        update_interval: UpdateInterval | None = None,
        space_id: UUID | None = None,
        owner_user_id: UUID | None = None,
        failure_state: CrawlerFailureState | None = None,
        sort: CrawlerTenantWebsiteInventorySort = (
            CrawlerTenantWebsiteInventorySort.RECENT_CRAWL
        ),
    ) -> CrawlerTenantWebsiteInventory:
        """Return every website in the tenant, filtered + paginated for governance.

        Why this lives next to `_crawler_failure_inventory` rather than as
        a separate "list-all-websites" repo: the failure-state classifier
        SQL CASE is shared, and the LEFT-JOIN attribution pattern is the
        same. The two reads are sibling lenses on the Websites table and
        belong in the same module.

        The query attaches space, collection, and owner via LEFT JOINs.
        Each LEFT JOIN intentionally constrains the joined-row tenant to
        equal the website tenant so a website pointing at a soft-deleted
        or cross-tenant row never leaks the other tenant's display name.
        """
        failure_state_expr = _website_failure_state_case()

        # Build the WHERE predicate as a single conjunction. Mirrors the
        # local pattern in `_crawler_failure_inventory` but uses
        # `sa.and_(*conditions)` at the call site so pyright sees a
        # concrete ColumnElement instead of an unpacked list[Unknown].
        conditions = [WebsitesTable.tenant_id == tenant_id]
        if update_interval is not None:
            conditions.append(WebsitesTable.update_interval == update_interval.value)
        if space_id is not None:
            conditions.append(WebsitesTable.space_id == space_id)
        if owner_user_id is not None:
            conditions.append(WebsitesTable.user_id == owner_user_id)
        if failure_state is CrawlerFailureState.AUTO_DISABLED:
            conditions.append(
                sa.and_(
                    WebsitesTable.update_interval == UpdateInterval.NEVER,
                    WebsitesTable.consecutive_failures
                    >= WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
                )
            )
        elif failure_state is CrawlerFailureState.BACKED_OFF:
            conditions.append(
                sa.and_(
                    WebsitesTable.consecutive_failures > 0,
                    WebsitesTable.next_retry_at.is_not(None),
                    WebsitesTable.update_interval != UpdateInterval.NEVER,
                )
            )

        # ILIKE OR-clause across url, name, owner_email. We rely on
        # case-insensitive ILIKE rather than lower(col) function calls
        # so postgres can still pick up a future pg_trgm GIN index on
        # these columns without rewriting the predicate. `escape_like`
        # treats user-typed `%` and `_` as literal characters (matches
        # the audit-log search behaviour) so a search for "100%" does
        # not silently widen the result set. When `search` is absent we
        # skip the Users join in the COUNT(*) below — see `count_from`.
        has_search = bool(search and search.strip())
        if has_search:
            assert search is not None
            safe = escape_like(search.strip())
            pattern = f"%{safe}%"
            conditions.append(
                sa.or_(
                    WebsitesTable.url.ilike(pattern, escape="\\"),
                    WebsitesTable.name.ilike(pattern, escape="\\"),
                    Users.email.ilike(pattern, escape="\\"),
                )
            )

        where_clause = sa.and_(*conditions)

        # The full FROM is needed for the rows query (attribution columns
        # come from Users/Spaces/Collections). The COUNT(*) only needs
        # Users when search is set — the OR-clause references Users.email.
        # All three joins are PK-based (Users.id, Spaces.id,
        # CollectionsTable.id are unique), so they never multiply rows;
        # the count over the join graph would be correct but the count
        # over the smaller FROM is cheaper. Both queries share the same
        # `where_clause` so the result set is identical.
        users_join = sa.outerjoin(
            WebsitesTable,
            Users,
            sa.and_(
                Users.id == WebsitesTable.user_id,
                Users.tenant_id == WebsitesTable.tenant_id,
            ),
        )
        rows_from = sa.outerjoin(
            users_join,
            Spaces,
            sa.and_(
                Spaces.id == WebsitesTable.space_id,
                Spaces.tenant_id == WebsitesTable.tenant_id,
            ),
        )
        rows_from = sa.outerjoin(
            rows_from,
            CollectionsTable,
            sa.and_(
                CollectionsTable.id == WebsitesTable.group_id,
                CollectionsTable.tenant_id == WebsitesTable.tenant_id,
            ),
        )

        count_from = users_join if has_search else WebsitesTable
        total_stmt = (
            sa.select(sa.func.count(WebsitesTable.id))
            .select_from(count_from)
            .where(where_clause)
        )
        total = int(await self.session.scalar(total_stmt) or 0)

        # order_by stays untyped — see the `conditions: list` comment above.
        # Every branch ends with a `WebsitesTable.id.asc()` tie-breaker so
        # pagination is stable when the primary sort key has duplicates.
        if sort is CrawlerTenantWebsiteInventorySort.SIZE_DESC:
            order_by = (
                WebsitesTable.size.desc(),
                WebsitesTable.id.asc(),
            )
        elif sort is CrawlerTenantWebsiteInventorySort.CONSECUTIVE_FAILURES:
            order_by = (
                WebsitesTable.consecutive_failures.desc(),
                WebsitesTable.updated_at.desc(),
                WebsitesTable.id.asc(),
            )
        elif sort is CrawlerTenantWebsiteInventorySort.URL:
            order_by = (
                sa.func.lower(WebsitesTable.url).asc(),
                WebsitesTable.id.asc(),
            )
        else:  # RECENT_CRAWL — the default, surfaces the staleness pattern
            order_by = (
                WebsitesTable.last_crawled_at.desc().nulls_last(),
                WebsitesTable.id.asc(),
            )

        rows_stmt = (
            sa.select(
                WebsitesTable.id.label("website_id"),
                WebsitesTable.url.label("url"),
                WebsitesTable.name.label("name"),
                WebsitesTable.created_at.label("created_at"),
                WebsitesTable.update_interval.label("update_interval"),
                WebsitesTable.crawl_type.label("crawl_type"),
                WebsitesTable.download_files.label("download_files"),
                WebsitesTable.http_auth_username.label("http_auth_username"),
                # `requires_http_auth` is derived: the username column is
                # non-null iff the website was configured with HTTP Basic
                # Auth. The encrypted password column is never read here
                # — the admin surface only needs to confirm the auth flag
                # and the username, never the secret.
                WebsitesTable.http_auth_username.is_not(None).label(
                    "requires_http_auth"
                ),
                failure_state_expr,
                WebsitesTable.consecutive_failures.label("consecutive_failures"),
                WebsitesTable.next_retry_at.label("next_retry_at"),
                WebsitesTable.last_crawled_at.label("last_crawled_at"),
                WebsitesTable.size.label("size_bytes"),
                WebsitesTable.user_id.label("owner_user_id"),
                Users.email.label("owner_email"),
                WebsitesTable.space_id.label("space_id"),
                Spaces.name.label("space_name"),
                WebsitesTable.group_id.label("collection_id"),
                CollectionsTable.name.label("collection_name"),
            )
            .select_from(rows_from)
            .where(where_clause)
            .order_by(*order_by)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(rows_stmt)
        items: list[CrawlerTenantWebsiteInventoryItem] = []
        for row in result.mappings():
            failure_state_value = row["failure_state"]
            classified_state = (
                CrawlerFailureState(str(failure_state_value))
                if failure_state_value is not None
                else None
            )
            # `crawl_type` is mapped on the table as `Mapped[CrawlType]`,
            # so SQLAlchemy returns the enum member directly. `str()` on
            # a `str, Enum` mixin returns the repr `"CrawlType.CRAWL"`,
            # not the value `"crawl"`, so we hand the enum straight to
            # the dataclass.
            raw_crawl_type = row["crawl_type"]
            crawl_type_value = (
                raw_crawl_type
                if isinstance(raw_crawl_type, CrawlType)
                else CrawlType(raw_crawl_type)
            )
            items.append(
                CrawlerTenantWebsiteInventoryItem(
                    website_id=row["website_id"],
                    url=str(row["url"]),
                    name=row["name"],
                    created_at=row["created_at"],
                    update_interval=UpdateInterval(str(row["update_interval"])),
                    crawl_type=crawl_type_value,
                    download_files=bool(row["download_files"]),
                    requires_http_auth=bool(row["requires_http_auth"]),
                    http_auth_username=row["http_auth_username"],
                    failure_state=classified_state,
                    consecutive_failures=int(row["consecutive_failures"]),
                    next_retry_at=row["next_retry_at"],
                    last_crawled_at=row["last_crawled_at"],
                    size_bytes=int(row["size_bytes"]),
                    owner_user_id=row["owner_user_id"],
                    owner_email=row["owner_email"],
                    space_id=row["space_id"],
                    space_name=row["space_name"],
                    collection_id=row["collection_id"],
                    collection_name=row["collection_name"],
                )
            )

        return CrawlerTenantWebsiteInventory(
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def scheduled_aggregate_for_tenant(
        self,
        *,
        tenant_id: UUID,
    ) -> CrawlerScheduledAggregate:
        return await self._scheduled_aggregate(tenant_id=tenant_id)

    async def scheduled_aggregate_for_sysadmin(
        self,
        *,
        tenant_id: UUID | None,
    ) -> CrawlerScheduledAggregate:
        return await self._scheduled_aggregate(tenant_id=tenant_id)

    async def _scheduled_aggregate(
        self,
        *,
        tenant_id: UUID | None,
    ) -> CrawlerScheduledAggregate:
        stmt = (
            sa.select(
                WebsitesTable.update_interval.label("update_interval"),
                sa.func.count(WebsitesTable.id).label("website_count"),
                sa.func.coalesce(sa.func.sum(WebsitesTable.size), 0).label(
                    "total_size_bytes"
                ),
            )
            .select_from(WebsitesTable)
            .group_by(WebsitesTable.update_interval)
        )
        if tenant_id is not None:
            stmt = stmt.where(WebsitesTable.tenant_id == tenant_id)

        result = await self.session.execute(stmt)

        counts_by_interval = {update_interval: 0 for update_interval in UpdateInterval}
        sizes_by_interval = {update_interval: 0 for update_interval in UpdateInterval}
        unparseable_update_interval_website_count = 0
        unparseable_update_interval_total_size_bytes = 0
        for row in result.mappings():
            website_count = int(row["website_count"])
            total_size_bytes = int(row["total_size_bytes"])
            try:
                update_interval = UpdateInterval(str(row["update_interval"]))
            except ValueError:
                unparseable_update_interval_website_count += website_count
                unparseable_update_interval_total_size_bytes += total_size_bytes
                continue

            counts_by_interval[update_interval] = website_count
            sizes_by_interval[update_interval] = total_size_bytes

        buckets = tuple(
            CrawlerScheduledIntervalBucket(
                update_interval=update_interval,
                website_count=counts_by_interval[update_interval],
                total_size_bytes=sizes_by_interval[update_interval],
            )
            for update_interval in sorted(UpdateInterval, key=lambda item: item.value)
        )

        return CrawlerScheduledAggregate(
            buckets=buckets,
            total_websites=(
                sum(bucket.website_count for bucket in buckets)
                + unparseable_update_interval_website_count
            ),
            total_size_bytes=(
                sum(bucket.total_size_bytes for bucket in buckets)
                + unparseable_update_interval_total_size_bytes
            ),
            unparseable_update_interval_website_count=(
                unparseable_update_interval_website_count
            ),
            unparseable_update_interval_total_size_bytes=(
                unparseable_update_interval_total_size_bytes
            ),
            tenant_id=tenant_id,
        )

    async def reset_crawl_circuit_breaker_for_tenant(
        self,
        *,
        website_id: UUID,
        tenant_id: UUID,
    ) -> CrawlCircuitResetResult:
        """Clear circuit-breaker counters for one website inside the tenant scope.

        Why: Operators currently recover from backed-off or auto-disabled websites
        only by editing the database directly. This method commits the same fields
        the worker reactor writes on a successful crawl, scoped strictly to one
        tenant, so the caller can replace DB surgery with a typed audited action.
        update_interval is intentionally untouched — a separate website-edit flow
        owns scheduling decisions for previously auto-disabled rows.
        """
        select_stmt = (
            sa.select(
                WebsitesTable.id,
                WebsitesTable.name,
                WebsitesTable.url,
                WebsitesTable.update_interval,
                WebsitesTable.consecutive_failures,
                WebsitesTable.next_retry_at,
            )
            .where(WebsitesTable.id == website_id)
            .where(WebsitesTable.tenant_id == tenant_id)
        )
        row = (await self.session.execute(select_stmt)).first()
        if row is None:
            return CrawlCircuitResetNotFound(website_id=website_id)

        previous_state = _classify_circuit_breaker_state(
            update_interval=UpdateInterval(str(row.update_interval)),
            consecutive_failures=int(row.consecutive_failures),
            next_retry_at=row.next_retry_at,
        )

        update_stmt = (
            sa.update(WebsitesTable)
            .where(WebsitesTable.id == website_id)
            .where(WebsitesTable.tenant_id == tenant_id)
            .values(consecutive_failures=0, next_retry_at=None)
        )
        await self.session.execute(update_stmt)

        display_name = row.name if row.name is not None else row.url
        return CrawlCircuitResetSucceeded(
            website=CrawlCircuitResetWebsite(
                id=row.id,
                name=str(display_name),
            ),
            previous_state=previous_state,
            previous_consecutive_failures=int(row.consecutive_failures),
            previous_next_retry_at=row.next_retry_at,
        )

    async def set_crawl_update_interval_for_tenant(
        self,
        *,
        website_id: UUID,
        tenant_id: UUID,
        new_update_interval: UpdateInterval,
    ) -> CrawlIntervalChangeResult:
        """Change one website's crawler update_interval inside a tenant scope.

        Why this is its own method rather than going through
        `WebsiteCRUDService.update_website`: the tenant admin route does not
        navigate through a Space actor — admin permission applies tenant-wide,
        not space-wide — so the space-based authorization in the CRUD service
        is the wrong gate. Constraining the SQL to `WHERE id = :id AND
        tenant_id = :tenant_id` is the canonical tenant-safe alternative.

        The method is idempotent: when the requested interval matches the
        stored value, no UPDATE runs and no audit row is written. Callers
        that need to record idempotent operator clicks should do so via a
        separate audit action; the audit trail for interval *changes* keeps
        signal-to-noise high.

        Auto-disable resume side effect: when an admin resumes a paused
        website (previous=NEVER + counters ≥ threshold + new=recurring),
        this method also clears `consecutive_failures` and `next_retry_at`
        in the same UPDATE. Without that side effect the next crawl failure
        would immediately re-trip auto-disable, leaving operators with no
        recovery path short of calling `/reset-circuit-breaker` as well.
        The cleared side effect is surfaced through `failure_state_cleared`
        on `CrawlIntervalChangeApplied` so audit metadata records the
        change honestly. The narrow gating (only NEVER → recurring at the
        threshold) preserves the distinction between "change schedule" and
        "reset circuit breaker" for non-auto-disable interval changes.
        """
        select_stmt = (
            sa.select(
                WebsitesTable.id,
                WebsitesTable.name,
                WebsitesTable.url,
                WebsitesTable.update_interval,
                WebsitesTable.consecutive_failures,
            )
            .where(WebsitesTable.id == website_id)
            .where(WebsitesTable.tenant_id == tenant_id)
        )
        row = (await self.session.execute(select_stmt)).first()
        if row is None:
            return CrawlIntervalChangeNotFound(website_id=website_id)

        previous_interval = UpdateInterval(str(row.update_interval))
        previous_consecutive_failures = int(row.consecutive_failures)
        display_name = row.name if row.name is not None else row.url
        website = CrawlIntervalChangeWebsite(
            id=row.id,
            name=str(display_name),
        )

        if previous_interval == new_update_interval:
            return CrawlIntervalChangeUnchanged(
                website=website,
                update_interval=previous_interval,
            )

        is_auto_disabled_resume = (
            previous_interval == UpdateInterval.NEVER
            and previous_consecutive_failures >= WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD
            and new_update_interval != UpdateInterval.NEVER
        )

        update_values: dict[str, object] = {
            "update_interval": new_update_interval.value
        }
        if is_auto_disabled_resume:
            update_values["consecutive_failures"] = 0
            update_values["next_retry_at"] = None

        update_stmt = (
            sa.update(WebsitesTable)
            .where(WebsitesTable.id == website_id)
            .where(WebsitesTable.tenant_id == tenant_id)
            .values(**update_values)
        )
        await self.session.execute(update_stmt)

        return CrawlIntervalChangeApplied(
            website=website,
            previous_update_interval=previous_interval,
            new_update_interval=new_update_interval,
            failure_state_cleared=is_auto_disabled_resume,
            previous_consecutive_failures=previous_consecutive_failures,
        )


def _classify_circuit_breaker_state(
    *,
    update_interval: UpdateInterval,
    consecutive_failures: int,
    next_retry_at: object | None,
) -> CrawlCircuitResetPreviousState:
    """Mirror the failure-inventory classifier so audit metadata matches the UI."""
    is_auto_disabled = (
        update_interval == UpdateInterval.NEVER
        and consecutive_failures >= WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD
    )
    if is_auto_disabled:
        return CrawlCircuitResetPreviousState.AUTO_DISABLED

    is_backed_off = (
        consecutive_failures > 0
        and next_retry_at is not None
        and update_interval != UpdateInterval.NEVER
    )
    if is_backed_off:
        return CrawlCircuitResetPreviousState.BACKED_OFF

    return CrawlCircuitResetPreviousState.HEALTHY
