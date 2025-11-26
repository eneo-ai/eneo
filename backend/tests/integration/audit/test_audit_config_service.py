"""Integration tests for audit category configuration service."""

import pytest

from intric.audit.application.audit_config_service import AuditConfigService
from intric.audit.infrastructure.audit_config_repository import AuditConfigRepositoryImpl
from intric.audit.schemas.audit_config_schemas import CategoryUpdate
from intric.worker.redis import get_redis

pytestmark = pytest.mark.integration


@pytest.fixture
async def seeded_tenant(db_session, test_tenant):
    """Seed the test tenant with all audit categories enabled."""
    async with db_session() as session:
        repo = AuditConfigRepositoryImpl(session)
        # Seed all 7 categories
        for category in [
            'admin_actions',
            'user_actions',
            'security_events',
            'file_operations',
            'integration_events',
            'system_actions',
            'audit_access',
        ]:
            await repo.update(test_tenant.id, category, True)
        await session.commit()
    return test_tenant




class TestAuditConfigRepository:
    """Test suite for AuditConfigRepository integration."""

    async def test_find_by_tenant_returns_all_seven_categories(
        self, db_session, seeded_tenant
    ):
        """Verify that find_by_tenant returns all 7 categories for a tenant."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            configs = await repo.find_by_tenant(seeded_tenant.id)

            assert len(configs) == 7, "Should return all 7 categories"

            categories = {config[0] for config in configs}
            expected_categories = {
                'admin_actions',
                'user_actions',
                'security_events',
                'file_operations',
                'integration_events',
                'system_actions',
                'audit_access',
            }
            assert categories == expected_categories

    async def test_find_by_tenant_all_enabled_by_default(
        self, db_session, seeded_tenant
    ):
        """Verify that all categories are enabled by default after migration."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            configs = await repo.find_by_tenant(seeded_tenant.id)

            # All categories should be enabled by default
            for category, enabled in configs:
                assert enabled is True, f"Category {category} should be enabled by default"

    async def test_find_by_tenant_and_category_existing(
        self, db_session, seeded_tenant
    ):
        """Test finding a specific category configuration."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            config = await repo.find_by_tenant_and_category(
                seeded_tenant.id, 'admin_actions'
            )

            assert config is not None
            assert config[0] == 'admin_actions'
            assert config[1] is True

    async def test_find_by_tenant_and_category_nonexistent(
        self, db_session, seeded_tenant
    ):
        """Test finding a category that doesn't exist returns None."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            config = await repo.find_by_tenant_and_category(
                seeded_tenant.id, 'nonexistent_category'
            )

            assert config is None

    async def test_update_category_disables_successfully(
        self, db_session, seeded_tenant
    ):
        """Test updating a category to disabled."""
        # Update in one session
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            await repo.update(seeded_tenant.id, 'admin_actions', False)
            await session.commit()

        # Verify in fresh session
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            config = await repo.find_by_tenant_and_category(
                seeded_tenant.id, 'admin_actions'
            )

            assert config is not None
            assert config[1] is False

    async def test_update_category_enables_successfully(
        self, db_session, seeded_tenant
    ):
        """Test updating a category to enabled after disabling."""
        # Disable then re-enable in one session
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            await repo.update(seeded_tenant.id, 'user_actions', False)
            await session.commit()

        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            await repo.update(seeded_tenant.id, 'user_actions', True)
            await session.commit()

        # Verify in fresh session
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            config = await repo.find_by_tenant_and_category(
                seeded_tenant.id, 'user_actions'
            )

            assert config is not None
            assert config[1] is True

    async def test_update_creates_if_not_exists_upsert(
        self, db_session, seeded_tenant
    ):
        """Test that update creates a new row if it doesn't exist (upsert behavior)."""
        # Update in one session
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            await repo.update(seeded_tenant.id, 'admin_actions', False)
            await session.commit()

        # Verify in fresh session
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            config = await repo.find_by_tenant_and_category(
                seeded_tenant.id, 'admin_actions'
            )

            assert config is not None
            assert config[1] is False


class TestAuditConfigService:
    """Test suite for AuditConfigService integration."""

    async def test_get_config_returns_all_categories_with_metadata(
        self, db_session, seeded_tenant
    ):
        """Verify get_config returns enriched category data."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)
            response = await service.get_config(seeded_tenant.id)

            assert len(response.categories) == 7

            # Verify all categories have required fields
            for category_config in response.categories:
                assert category_config.category in {
                    'admin_actions',
                    'user_actions',
                    'security_events',
                    'file_operations',
                    'integration_events',
                    'system_actions',
                    'audit_access',
                }
                assert isinstance(category_config.enabled, bool)
                assert len(category_config.description) > 0
                assert category_config.action_count > 0
                assert len(category_config.example_actions) > 0
                assert len(category_config.example_actions) <= 3

    async def test_get_config_admin_actions_has_13_actions(
        self, db_session, seeded_tenant
    ):
        """Verify admin_actions category has correct action count."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)
            response = await service.get_config(seeded_tenant.id)

            admin_config = next(
                c for c in response.categories if c.category == 'admin_actions'
            )
            assert admin_config.action_count == 13

    async def test_update_config_single_category(
        self, db_session, seeded_tenant
    ):
        """Test updating a single category."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)

            updates = [CategoryUpdate(category='file_operations', enabled=False)]
            response = await service.update_config(seeded_tenant.id, updates)

            file_ops_config = next(
                c for c in response.categories if c.category == 'file_operations'
            )
            assert file_ops_config.enabled is False

            # Other categories should remain enabled
            admin_config = next(
                c for c in response.categories if c.category == 'admin_actions'
            )
            assert admin_config.enabled is True

    async def test_update_config_multiple_categories(
        self, db_session, seeded_tenant
    ):
        """Test updating multiple categories at once."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)

            updates = [
                CategoryUpdate(category='admin_actions', enabled=False),
                CategoryUpdate(category='security_events', enabled=False),
                CategoryUpdate(category='file_operations', enabled=False),
            ]

            response = await service.update_config(seeded_tenant.id, updates)

            disabled_categories = {
                c.category for c in response.categories if not c.enabled
            }
            assert disabled_categories == {
                'admin_actions',
                'security_events',
                'file_operations',
            }

    async def test_is_category_enabled_default_true(
        self, db_session, seeded_tenant
    ):
        """Test that is_category_enabled returns True by default."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)

            enabled = await service.is_category_enabled(
                seeded_tenant.id, 'admin_actions'
            )
            assert enabled is True

    async def test_is_category_enabled_after_disable(
        self, db_session, seeded_tenant
    ):
        """Test that is_category_enabled returns False after disabling."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)

            # Disable admin_actions
            updates = [CategoryUpdate(category='admin_actions', enabled=False)]
            await service.update_config(seeded_tenant.id, updates)

            # Check if it's disabled
            enabled = await service.is_category_enabled(
                seeded_tenant.id, 'admin_actions'
            )
            assert enabled is False

    async def test_is_category_enabled_uses_redis_cache(
        self, db_session, seeded_tenant
    ):
        """Test that is_category_enabled uses Redis cache on second call."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)
            redis = get_redis()

            # First call - cache miss (database query)
            enabled1 = await service.is_category_enabled(
                seeded_tenant.id, 'user_actions'
            )
            assert enabled1 is True

            # Verify cache was set
            cache_key = f"audit_config:{seeded_tenant.id}:user_actions"
            cached_value = await redis.get(cache_key)
            assert cached_value is not None
            assert cached_value.decode('utf-8') == "true"

            # Second call - cache hit (no database query)
            enabled2 = await service.is_category_enabled(
                seeded_tenant.id, 'user_actions'
            )
            assert enabled2 is True

    async def test_cache_invalidation_on_update(
        self, db_session, seeded_tenant
    ):
        """Test that Redis cache is invalidated when config is updated."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)
            redis = get_redis()

            # Populate cache
            await service.is_category_enabled(
                seeded_tenant.id, 'security_events'
            )

            cache_key = f"audit_config:{seeded_tenant.id}:security_events"

            # Verify cache exists
            cached_before = await redis.get(cache_key)
            assert cached_before is not None

            # Update the category
            updates = [CategoryUpdate(category='security_events', enabled=False)]
            await service.update_config(seeded_tenant.id, updates)

            # Verify cache was invalidated
            cached_after = await redis.get(cache_key)
            assert cached_after is None

            # Next call should query database and set new cache value
            enabled = await service.is_category_enabled(
                seeded_tenant.id, 'security_events'
            )
            assert enabled is False

            # Verify new cache value
            cached_new = await redis.get(cache_key)
            assert cached_new is not None
            assert cached_new.decode('utf-8') == "false"

    async def test_is_category_enabled_unknown_category_defaults_true(
        self, db_session, seeded_tenant
    ):
        """Test that unknown categories default to enabled for backward compatibility."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)

            enabled = await service.is_category_enabled(
                seeded_tenant.id, 'unknown_category'
            )
            assert enabled is True

    async def test_cache_ttl_is_60_seconds(
        self, db_session, seeded_tenant
    ):
        """Test that cache TTL is set to 60 seconds."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)
            redis = get_redis()

            # Trigger cache population
            await service.is_category_enabled(
                seeded_tenant.id, 'audit_access'
            )

            cache_key = f"audit_config:{seeded_tenant.id}:audit_access"
            ttl = await redis.ttl(cache_key)

            # TTL should be around 60 seconds (allow some variance for execution time)
            assert 55 <= ttl <= 60


class TestTenantIsolation:
    """Test suite for multi-tenancy isolation and category independence."""

    async def test_categories_are_independent_within_tenant(
        self, db_session, seeded_tenant
    ):
        """Verify that disabling one category doesn't affect others within same tenant."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)

            # Disable admin_actions
            await service.update_config(
                seeded_tenant.id,
                [CategoryUpdate(category='admin_actions', enabled=False)]
            )

            # Verify admin_actions is disabled
            enabled_admin = await service.is_category_enabled(
                seeded_tenant.id, 'admin_actions'
            )
            assert enabled_admin is False

            # Verify other categories remain enabled
            enabled_user = await service.is_category_enabled(
                seeded_tenant.id, 'user_actions'
            )
            assert enabled_user is True

            enabled_security = await service.is_category_enabled(
                seeded_tenant.id, 'security_events'
            )
            assert enabled_security is True

    async def test_cache_keys_are_category_specific(
        self, db_session, seeded_tenant
    ):
        """Verify that cache invalidation is category-specific."""
        async with db_session() as session:
            repo = AuditConfigRepositoryImpl(session)
            service = AuditConfigService(repository=repo)
            redis = get_redis()

            # Populate cache for two different categories
            await service.is_category_enabled(
                seeded_tenant.id, 'user_actions'
            )
            await service.is_category_enabled(
                seeded_tenant.id, 'file_operations'
            )

            # Verify both are cached
            cache_key1 = f"audit_config:{seeded_tenant.id}:user_actions"
            cache_key2 = f"audit_config:{seeded_tenant.id}:file_operations"

            cached1_before = await redis.get(cache_key1)
            cached2_before = await redis.get(cache_key2)

            assert cached1_before is not None
            assert cached2_before is not None

            # Update only user_actions
            await service.update_config(
                seeded_tenant.id,
                [CategoryUpdate(category='user_actions', enabled=False)]
            )

            # Verify user_actions cache was invalidated
            cached1_after = await redis.get(cache_key1)
            assert cached1_after is None

            # Verify file_operations cache is still present
            cached2_after = await redis.get(cache_key2)
            assert cached2_after is not None
