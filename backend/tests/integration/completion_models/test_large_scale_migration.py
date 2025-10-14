"""
Large-scale migration test to simulate production environment.

This test is designed for local testing only and creates 100+ entities
to verify migration performance and correctness at scale.

NOTE: This test is NOT intended to be part of the regular CI/CD pipeline
due to its scale and runtime. Run manually when testing migration logic.

USAGE:
    # Run the large-scale migration test
    pytest backend/tests/integration/completion_models/test_large_scale_migration.py -v -s

CONFIGURATION:
Adjust these numbers to control the scale of the test. Higher numbers will
take longer but provide better stress testing. Configuration values are
defined below (lines 39-42).
"""
import pytest
from sqlalchemy import select

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.app_table import Apps
from intric.database.tables.service_table import Services
from intric.database.tables.spaces_table import SpacesCompletionModels

# =============================================================================
# TEST CONFIGURATION - Adjust these values to control test scale
# =============================================================================

# Default configuration (1200 entities)
ASSISTANTS = 500
APPS = 300
SERVICES = 250
SPACES = 150

# For even larger stress tests, you can increase these values:
# ASSISTANTS = 2000
# APPS = 1000
# SERVICES = 500
# SPACES = 300

# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestLargeScaleMigration:
    """
    Test migration with production-scale data volumes.

    Note: The cleanup_database fixture from conftest.py automatically runs after
    each test, ensuring a fresh database seed for each test run.
    """

    async def test_large_scale_migration(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        app_factory,
        service_factory,
        space_factory,
        admin_user,
        admin_user_api_key,
        client,
    ):
        """
        Test large-scale migration at production scale.

        Creates large volumes of entities across all types and performs a complete
        migration via the API, verifying database state, migration history, and performance metrics.

        Entity counts are configurable at the top of this file via:
        ASSISTANTS, APPS, SERVICES, SPACES

        Default: 1200 total entities (500 assistants, 300 apps, 250 services, 150 spaces)
        """
        # Generate unique model names to avoid conflicts from previous failed test runs
        import time
        test_run_id = int(time.time() * 1000)  # millisecond timestamp for uniqueness

        async with db_container() as container:
            session = container.session()

            print("\n" + "="*80)
            print(f"LARGE-SCALE MIGRATION TEST VIA API ({ASSISTANTS + APPS + SERVICES + SPACES} entities)")
            print("="*80)

            # Setup: Create models with unique names
            print("\n[1/5] Creating completion models...")
            old_model = await completion_model_factory(
                session,
                f"gpt-3.5-turbo-{test_run_id}",
                nickname="GPT-3.5 Turbo",
                provider="openai"
            )
            new_model = await completion_model_factory(
                session,
                f"gpt-4-{test_run_id}",
                nickname="GPT-4",
                provider="openai"
            )
            other_model = await completion_model_factory(
                session,
                f"claude-3-{test_run_id}",
                nickname="Claude 3",
                provider="anthropic"
            )
            print(f"✓ Created 3 models with unique names (run ID: {test_run_id})")
            print(f"  - Old model: {old_model.id}")
            print(f"  - New model: {new_model.id}")
            print(f"  - Other model: {other_model.id}")

            # Create large volumes of entities
            print("\n[2/5] Creating test entities (this will take a moment)...")

            # Create assistants with progress tracking
            print(f"  - Creating {ASSISTANTS} assistants...", end="", flush=True)
            for i in range(ASSISTANTS):
                await assistant_factory(
                    session,
                    f"Assistant {i}",
                    old_model.id,
                    kwargs={"temperature": 0.7} if i % 10 == 0 else {}
                )
            print(" ✓")

            # Create apps
            print(f"  - Creating {APPS} apps...", end="", flush=True)
            for i in range(APPS):
                await app_factory(session, f"App {i}", old_model.id)
            print(" ✓")

            # Create services
            print(f"  - Creating {SERVICES} services...", end="", flush=True)
            for i in range(SERVICES):
                await service_factory(session, f"Service {i}", old_model.id)
            print(" ✓")

            # Create spaces with varied configurations
            print(f"  - Creating {SPACES} spaces...", end="", flush=True)
            # Calculate distribution: 67% single old_model, 27% mixed, 6% other only
            single_old_count = int(SPACES * 0.67)
            mixed_count = int(SPACES * 0.27)
            spaces_with_old_model = single_old_count + mixed_count
            for i in range(SPACES):
                if i < single_old_count:
                    models = [old_model.id]
                elif i < spaces_with_old_model:
                    models = [old_model.id, other_model.id]
                else:
                    models = [other_model.id]
                await space_factory(session, f"Space {i}", models)
            print(" ✓")

            total_entities = ASSISTANTS + APPS + SERVICES + spaces_with_old_model
            total_entities_created = ASSISTANTS + APPS + SERVICES + SPACES
            print(f"\n✓ Created {total_entities_created} total entities:")
            print(f"  - {ASSISTANTS} assistants")
            print(f"  - {APPS} apps")
            print(f"  - {SERVICES} services")
            print(f"  - {SPACES} spaces")
            print(f"  - {spaces_with_old_model} spaces using old model (others use different models)")

            # Verify initial state
            print("\n[3/5] Verifying initial state...")
            stmt = select(Assistants).where(Assistants.completion_model_id == old_model.id)
            initial_assistants = len((await session.execute(stmt)).scalars().all())

            stmt = select(Apps).where(Apps.completion_model_id == old_model.id)
            initial_apps = len((await session.execute(stmt)).scalars().all())

            stmt = select(Services).where(Services.completion_model_id == old_model.id)
            initial_services = len((await session.execute(stmt)).scalars().all())

            stmt = select(SpacesCompletionModels).where(
                SpacesCompletionModels.completion_model_id == old_model.id
            )
            initial_spaces = len((await session.execute(stmt)).scalars().all())

            print(f"  - Assistants using old model: {initial_assistants}")
            print(f"  - Apps using old model: {initial_apps}")
            print(f"  - Services using old model: {initial_services}")
            print(f"  - Spaces with old model: {initial_spaces}")

            assert initial_assistants == ASSISTANTS
            assert initial_apps == APPS
            assert initial_services == SERVICES
            assert initial_spaces == spaces_with_old_model

            # Save model IDs before exiting the session context
            old_model_id = old_model.id
            new_model_id = new_model.id

        # Perform migration via API
        print("\n[4/5] Performing large-scale migration via API...")
        print(f"  - From model: {old_model_id}")
        print(f"  - To model: {new_model_id}")

        import time
        start_time = time.time()

        # Call the migration API endpoint
        response = await client.post(
            f"/api/v1/completion-models/{old_model_id}/migrate",
            headers={"X-API-Key": admin_user_api_key.key},
            json={
                "to_model_id": str(new_model_id),
                "entity_types": ["assistants", "apps", "services", "spaces"],
                "confirm_migration": True,
            },
        )

        end_time = time.time()
        duration = end_time - start_time

        # Verify API response
        assert response.status_code == 200, f"Migration API failed with {response.status_code}: {response.text}"
        result = response.json()

        print(f"\n✓ Migration completed in {duration:.2f} seconds")
        print(f"  - Migration speed: {result['migrated_count'] / duration:.1f} entities/second")
        print(f"  - Migration ID: {result['migration_id']}")

        # Verify API response
        print("\n[5/5] Verifying migration results...")
        assert result["success"] is True, "Migration should succeed"
        assert result["failed_count"] == 0, "No migrations should fail"
        assert result["migrated_count"] == total_entities, \
            f"Expected {total_entities} migrations, got {result['migrated_count']}"

        print(f"  ✓ API returned success: {result['migrated_count']} entities migrated")
        print(f"    - {result['details']['assistants']} assistants")
        print(f"    - {result['details']['apps']} apps")
        print(f"    - {result['details']['services']} services")
        print(f"    - {result['details']['spaces']} spaces")

        # Verify database state
        async with db_container() as container:
            session = container.session()

            print("\n  Verifying database state after migration...")

            # Verify NO entities remain on old model
            stmt = select(Assistants).where(Assistants.completion_model_id == old_model_id)
            remaining_assistants = (await session.execute(stmt)).scalars().all()
            assert len(remaining_assistants) == 0

            stmt = select(Apps).where(Apps.completion_model_id == old_model_id)
            remaining_apps = (await session.execute(stmt)).scalars().all()
            assert len(remaining_apps) == 0

            stmt = select(Services).where(Services.completion_model_id == old_model_id)
            remaining_services = (await session.execute(stmt)).scalars().all()
            assert len(remaining_services) == 0

            stmt = select(SpacesCompletionModels).where(
                SpacesCompletionModels.completion_model_id == old_model_id
            )
            remaining_spaces = (await session.execute(stmt)).scalars().all()
            assert len(remaining_spaces) == 0

            print("  ✓ Verified: 0 entities remain on old model")

            # Verify all entities migrated to new model
            stmt = select(Assistants).where(Assistants.completion_model_id == new_model_id)
            migrated_assistants = (await session.execute(stmt)).scalars().all()
            assert len(migrated_assistants) == ASSISTANTS

            stmt = select(Apps).where(Apps.completion_model_id == new_model_id)
            migrated_apps = (await session.execute(stmt)).scalars().all()
            assert len(migrated_apps) == APPS

            stmt = select(Services).where(Services.completion_model_id == new_model_id)
            migrated_services = (await session.execute(stmt)).scalars().all()
            assert len(migrated_services) == SERVICES

            stmt = select(SpacesCompletionModels).where(
                SpacesCompletionModels.completion_model_id == new_model_id
            )
            migrated_spaces = (await session.execute(stmt)).scalars().all()
            assert len(migrated_spaces) == spaces_with_old_model

            print(f"  ✓ Verified: {len(migrated_assistants)} assistants migrated to new model")
            print(f"  ✓ Verified: {len(migrated_apps)} apps migrated to new model")
            print(f"  ✓ Verified: {len(migrated_services)} services migrated to new model")
            print(f"  ✓ Verified: {len(migrated_spaces)} spaces migrated to new model")

            # Verify migration history was recorded
            print("\n  Verifying migration history...")
            history_service = container.completion_model_migration_history_service()
            history = await history_service.get_migration_history_by_id(
                result['migration_id'],
                admin_user.tenant_id
            )
            assert history is not None, "Migration history not found"
            assert str(history.from_model_id) == str(old_model_id)
            assert str(history.to_model_id) == str(new_model_id)
            assert history.migrated_count == total_entities
            print("  ✓ Migration history recorded successfully")

        # Final summary
        print("\n" + "="*80)
        print("LARGE-SCALE MIGRATION TEST - PASSED ✓")
        print("="*80)
        print(f"Successfully migrated {result['migrated_count']} entities in {duration:.2f}s")
        print(f"Performance: {result['migrated_count'] / duration:.1f} entities/second")
        print("Breakdown:")
        print(f"  - {result['details']['assistants']} assistants")
        print(f"  - {result['details']['apps']} apps")
        print(f"  - {result['details']['services']} services")
        print(f"  - {result['details']['spaces']} spaces")
        print("="*80 + "\n")
