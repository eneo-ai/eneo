from dataclasses import dataclass

from eneo.integration.presentation.models import (
    IntegrationPreviewData,
    SharePointTreeItem,
)
from eneo.integration.sharepoint_fixture.catalog import (
    SITES_BY_SCENARIO,
    TREE_BY_PROFILE,
    FixtureSite,
    FixtureTreeNode,
)
from eneo.integration.sharepoint_fixture.models import (
    SharePointFixturePreviewResponse,
    SharePointFixtureScenario,
    SharePointFixtureTreeResponse,
)
from eneo.main.exceptions import BadRequestException, NotFoundException


@dataclass(frozen=True)
class _FolderLocation:
    node: FixtureTreeNode
    path: str
    parent_id: str | None


class SharePointFixtureService:
    """Serves deterministic fixtures without depending on Graph or auth services."""

    def get_preview(
        self, scenario: SharePointFixtureScenario
    ) -> SharePointFixturePreviewResponse:
        items = [self._to_preview_item(site) for site in SITES_BY_SCENARIO[scenario]]
        return SharePointFixturePreviewResponse(scenario=scenario, items=items)

    def get_tree(
        self,
        scenario: SharePointFixtureScenario,
        *,
        site_id: str | None,
        drive_id: str | None,
        folder_id: str | None = None,
        folder_path: str = "",
    ) -> SharePointFixtureTreeResponse:
        site = self._find_site(scenario, site_id=site_id, drive_id=drive_id)
        roots = TREE_BY_PROFILE[site.tree_profile]

        current_path = "/"
        parent_id = None
        current_nodes = roots
        if folder_id:
            location = self._find_folder(roots, folder_id)
            if location is None:
                raise NotFoundException(
                    f"Unknown SharePoint fixture folder: {folder_id}"
                )
            current_path = location.path
            parent_id = location.parent_id
            current_nodes = location.node.children

            requested_path = self._normalize_path(folder_path)
            if folder_path and requested_path != current_path:
                raise BadRequestException(
                    "Fixture folder_path does not match the requested folder_id"
                )

        items = [
            self._to_tree_item(site=site, node=node, parent_path=current_path)
            for node in current_nodes
        ]
        resolved_drive_id = (
            site.key
            if site.resource_type == "onedrive"
            else f"fixture-drive-for-{site.key.removeprefix('fixture-site-')}"
        )
        return SharePointFixtureTreeResponse(
            scenario=scenario,
            items=items,
            current_path=current_path,
            parent_id=parent_id,
            drive_id=resolved_drive_id,
            site_id=site.key if site.resource_type == "site" else None,
        )

    @staticmethod
    def _to_preview_item(site: FixtureSite) -> IntegrationPreviewData:
        return IntegrationPreviewData(
            key=site.key,
            type=site.resource_type,
            name=site.name,
            url=site.url,
            category=site.category,
        )

    @staticmethod
    def _find_site(
        scenario: SharePointFixtureScenario,
        *,
        site_id: str | None,
        drive_id: str | None,
    ) -> FixtureSite:
        if bool(site_id) == bool(drive_id):
            raise BadRequestException("Provide exactly one fixture site_id or drive_id")

        requested_key = site_id or drive_id
        requested_type = "site" if site_id else "onedrive"
        for site in SITES_BY_SCENARIO[scenario]:
            if site.key == requested_key and site.resource_type == requested_type:
                return site

        raise NotFoundException(f"Unknown SharePoint fixture resource: {requested_key}")

    @classmethod
    def _find_folder(
        cls,
        nodes: tuple[FixtureTreeNode, ...],
        folder_id: str,
        *,
        parent_path: str = "/",
        parent_id: str | None = None,
    ) -> _FolderLocation | None:
        for node in nodes:
            node_path = cls._join_path(parent_path, node.name)
            if node.id == folder_id and node.item_type == "folder":
                return _FolderLocation(
                    node=node,
                    path=node_path,
                    parent_id=parent_id,
                )
            location = cls._find_folder(
                node.children,
                folder_id,
                parent_path=node_path,
                parent_id=node.id,
            )
            if location is not None:
                return location
        return None

    @classmethod
    def _to_tree_item(
        cls,
        *,
        site: FixtureSite,
        node: FixtureTreeNode,
        parent_path: str,
    ) -> SharePointTreeItem:
        path = cls._join_path(parent_path, node.name)
        return SharePointTreeItem(
            id=node.id,
            name=node.name,
            type=node.item_type,
            path=path,
            has_children=bool(node.children),
            size=node.size,
            modified=node.modified,
            web_url=(f"https://sharepoint-fixture.invalid/item/{site.key}/{node.id}"),
        )

    @staticmethod
    def _normalize_path(path: str) -> str:
        segments = [segment for segment in path.split("/") if segment]
        return f"/{'/'.join(segments)}" if segments else "/"

    @staticmethod
    def _join_path(parent_path: str, name: str) -> str:
        normalized_parent = parent_path.rstrip("/")
        return f"{normalized_parent}/{name}" if normalized_parent else f"/{name}"
