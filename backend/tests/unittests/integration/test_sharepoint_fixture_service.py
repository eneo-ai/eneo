from collections.abc import Iterator

import pytest

from eneo.integration.sharepoint_fixture.catalog import (
    SITES_BY_SCENARIO,
    TREE_BY_PROFILE,
    FixtureTreeNode,
)
from eneo.integration.sharepoint_fixture.models import SharePointFixtureScenario
from eneo.integration.sharepoint_fixture.router import (
    get_sharepoint_fixture_preview,
    get_sharepoint_fixture_tree,
    require_sharepoint_fixture_mode,
)
from eneo.integration.sharepoint_fixture.service import SharePointFixtureService
from eneo.main.config import Settings
from eneo.main.exceptions import BadRequestException, NotFoundException


def _settings(*, environment: str, enabled: bool) -> Settings:
    return Settings.model_construct(
        environment=environment,
        sharepoint_fixture_mode_enabled=enabled,
    )


def _walk(nodes: tuple[FixtureTreeNode, ...]) -> Iterator[FixtureTreeNode]:
    for node in nodes:
        yield node
        yield from _walk(node.children)


class TestSharePointFixtureSafety:
    def test_fixture_mode_requires_explicit_flag_and_safe_environment(self):
        require_sharepoint_fixture_mode(
            _settings(environment="development", enabled=True)
        )

        for settings in (
            _settings(environment="development", enabled=False),
            _settings(environment="production", enabled=True),
            _settings(environment="staging", enabled=True),
        ):
            with pytest.raises(NotFoundException):
                require_sharepoint_fixture_mode(settings)

    def test_all_fixture_identifiers_and_urls_are_unmistakable(self):
        sites = {
            site.key: site
            for scenario_sites in SITES_BY_SCENARIO.values()
            for site in scenario_sites
        }
        assert sites
        assert all(key.startswith("fixture-") for key in sites)
        assert all(
            site.url.startswith("https://sharepoint-fixture.invalid/")
            for site in sites.values()
        )

        nodes = [node for roots in TREE_BY_PROFILE.values() for node in _walk(roots)]
        assert nodes
        assert all(node.id.startswith("fixture-") for node in nodes)

    async def test_fixture_routes_need_no_integration_or_graph_context(self):
        preview = await get_sharepoint_fixture_preview(
            SharePointFixtureScenario.REPRESENTATIVE
        )
        tree = await get_sharepoint_fixture_tree(
            SharePointFixtureScenario.REPRESENTATIVE,
            site_id="fixture-site-product-development",
            drive_id=None,
            folder_id=None,
            folder_path="",
        )

        assert preview.fixture is True
        assert tree.fixture is True
        assert tree.site_id == "fixture-site-product-development"


class TestSharePointFixturePreview:
    service = SharePointFixtureService()

    def test_representative_scenario_covers_realistic_ui_edge_cases(self):
        response = self.service.get_preview(SharePointFixtureScenario.REPRESENTATIVE)

        assert response.fixture is True
        assert response.count == 12
        assert {item.category for item in response.items} == {
            "my_teams",
            "other_sites",
            "onedrive",
        }
        assert sum(item.name == "Ekonomi" for item in response.items) == 2
        assert any(
            "å" in item.name.lower() or "ö" in item.name.lower()
            for item in response.items
        )
        assert any(len(item.name) > 70 for item in response.items)

    def test_large_tenant_is_deterministic_and_exercises_volume(self):
        first = self.service.get_preview(SharePointFixtureScenario.LARGE_TENANT)
        second = self.service.get_preview(SharePointFixtureScenario.LARGE_TENANT)

        assert first == second
        assert first.count == 152
        assert len({item.key for item in first.items}) == first.count
        assert sum(item.category == "my_teams" for item in first.items) >= 30

    def test_empty_scenario_has_no_preview_results(self):
        response = self.service.get_preview(SharePointFixtureScenario.EMPTY)

        assert response.fixture is True
        assert response.count == 0
        assert response.items == []


class TestSharePointFixtureTree:
    service = SharePointFixtureService()
    scenario = SharePointFixtureScenario.REPRESENTATIVE
    site_id = "fixture-site-product-development"

    def test_root_contains_files_folders_and_boundary_data(self):
        response = self.service.get_tree(
            self.scenario,
            site_id=self.site_id,
            drive_id=None,
        )

        assert response.fixture is True
        assert response.current_path == "/"
        assert response.site_id == self.site_id
        assert response.drive_id.startswith("fixture-drive-for-")
        assert {item.type for item in response.items} == {"file", "folder"}
        assert any(item.size == 0 for item in response.items)
        assert any(
            item.size is not None and item.size > 40_000_000 for item in response.items
        )
        assert all(
            item.web_url and ".invalid/" in item.web_url for item in response.items
        )

    def test_nested_and_empty_folders_preserve_navigation_contract(self):
        nested = self.service.get_tree(
            self.scenario,
            site_id=self.site_id,
            drive_id=None,
            folder_id="fixture-folder-policies",
            folder_path="/01 – Styrande dokument/Policyer",
        )
        empty = self.service.get_tree(
            self.scenario,
            site_id=self.site_id,
            drive_id=None,
            folder_id="fixture-folder-project-empty",
            folder_path="/Projekt/Öresund – tom projektmapp",
        )

        assert nested.current_path == "/01 – Styrande dokument/Policyer"
        assert nested.parent_id == "fixture-folder-governance"
        assert {item.type for item in nested.items} == {"file"}
        assert empty.items == []
        assert empty.current_path.endswith("Öresund – tom projektmapp")

    def test_onedrive_uses_drive_contract_without_site_id(self):
        response = self.service.get_tree(
            self.scenario,
            site_id=None,
            drive_id="fixture-drive-alexandra-nilsson",
        )

        assert response.site_id is None
        assert response.drive_id == "fixture-drive-alexandra-nilsson"
        assert any(item.name == "Dokument" for item in response.items)

    def test_empty_site_has_an_empty_root_tree(self):
        response = self.service.get_tree(
            self.scenario,
            site_id="fixture-site-empty-collaboration",
            drive_id=None,
        )

        assert response.current_path == "/"
        assert response.items == []

    def test_rejects_ambiguous_unknown_and_mismatched_navigation(self):
        with pytest.raises(BadRequestException):
            self.service.get_tree(
                self.scenario,
                site_id=self.site_id,
                drive_id="fixture-drive-alexandra-nilsson",
            )

        with pytest.raises(NotFoundException):
            self.service.get_tree(
                self.scenario,
                site_id="fixture-site-does-not-exist",
                drive_id=None,
            )

        with pytest.raises(BadRequestException):
            self.service.get_tree(
                self.scenario,
                site_id=self.site_id,
                drive_id=None,
                folder_id="fixture-folder-policies",
                folder_path="/wrong/path",
            )
