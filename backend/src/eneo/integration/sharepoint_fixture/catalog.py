"""Deterministic data for validating the SharePoint import UI.

All identifiers use a ``fixture-`` prefix and all URLs use the reserved
``.invalid`` top-level domain. This makes accidental use outside the fixture
API visible and prevents test links from resolving to a real Microsoft tenant.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from eneo.integration.sharepoint_fixture.models import SharePointFixtureScenario

FixtureCategory = Literal["my_teams", "other_sites", "onedrive"]
FixtureResourceType = Literal["site", "onedrive"]
FixtureTreeItemType = Literal["file", "folder"]
FixtureTreeProfile = Literal["standard", "engineering", "onedrive", "empty"]


@dataclass(frozen=True)
class FixtureSite:
    key: str
    name: str
    resource_type: FixtureResourceType
    category: FixtureCategory
    tree_profile: FixtureTreeProfile
    url: str


@dataclass(frozen=True)
class FixtureTreeNode:
    id: str
    name: str
    item_type: FixtureTreeItemType
    modified: datetime
    size: int | None = None
    children: tuple["FixtureTreeNode", ...] = ()


def _modified(year: int, month: int, day: int, hour: int = 8) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


REPRESENTATIVE_SITES: tuple[FixtureSite, ...] = (
    FixtureSite(
        key="fixture-site-leadership-se",
        name="Ledningsgrupp Sverige",
        resource_type="site",
        category="my_teams",
        tree_profile="standard",
        url="https://sharepoint-fixture.invalid/sites/leadership-se",
    ),
    FixtureSite(
        key="fixture-site-project-aurora",
        name="Projekt Aurora – extern samverkan",
        resource_type="site",
        category="my_teams",
        tree_profile="engineering",
        url="https://sharepoint-fixture.invalid/sites/project-aurora",
    ),
    FixtureSite(
        key="fixture-site-product-development",
        name="Produkt & utveckling",
        resource_type="site",
        category="my_teams",
        tree_profile="engineering",
        url="https://sharepoint-fixture.invalid/sites/product-development",
    ),
    FixtureSite(
        key="fixture-site-sales-stockholm",
        name="Försäljning – Stockholm",
        resource_type="site",
        category="my_teams",
        tree_profile="standard",
        url="https://sharepoint-fixture.invalid/sites/sales-stockholm",
    ),
    FixtureSite(
        key="fixture-site-hr-people",
        name="HR & People",
        resource_type="site",
        category="other_sites",
        tree_profile="standard",
        url="https://sharepoint-fixture.invalid/sites/hr-people",
    ),
    FixtureSite(
        key="fixture-site-information-security",
        name="Informationssäkerhet och dataskydd",
        resource_type="site",
        category="other_sites",
        tree_profile="standard",
        url="https://sharepoint-fixture.invalid/sites/information-security",
    ),
    FixtureSite(
        key="fixture-site-customer-programme-north",
        name="Kundprogram Norr – gemensam projekt- och leveransyta för externa samarbeten",
        resource_type="site",
        category="other_sites",
        tree_profile="engineering",
        url="https://sharepoint-fixture.invalid/sites/customer-programme-north",
    ),
    FixtureSite(
        key="fixture-site-archive-2019-2025",
        name="Arkiv 2019–2025",
        resource_type="site",
        category="other_sites",
        tree_profile="standard",
        url="https://sharepoint-fixture.invalid/sites/archive-2019-2025",
    ),
    FixtureSite(
        key="fixture-site-finance-central",
        name="Ekonomi",
        resource_type="site",
        category="other_sites",
        tree_profile="standard",
        url="https://sharepoint-fixture.invalid/sites/finance-central",
    ),
    FixtureSite(
        key="fixture-site-finance-south",
        name="Ekonomi",
        resource_type="site",
        category="other_sites",
        tree_profile="standard",
        url="https://sharepoint-fixture.invalid/sites/finance-south",
    ),
    FixtureSite(
        key="fixture-site-empty-collaboration",
        name="Ny samarbetsyta (tom)",
        resource_type="site",
        category="other_sites",
        tree_profile="empty",
        url="https://sharepoint-fixture.invalid/sites/empty-collaboration",
    ),
    FixtureSite(
        key="fixture-drive-alexandra-nilsson",
        name="Alexandra Nilssons OneDrive",
        resource_type="onedrive",
        category="onedrive",
        tree_profile="onedrive",
        url="https://sharepoint-fixture.invalid/personal/alexandra-nilsson",
    ),
)


_LARGE_DEPARTMENTS = (
    "Ekonomi",
    "HR & People",
    "IT-drift",
    "Kommunikation",
    "Kundservice",
    "Produktutveckling",
    "Försäljning",
    "Informationssäkerhet",
    "Juridik",
    "Verksamhetsutveckling",
)
_LARGE_REGIONS = (
    "Göteborg",
    "Malmö",
    "Norr",
    "Stockholm",
    "Syd",
    "Umeå",
    "Uppsala",
    "Öresund",
)


def _large_tenant_site(index: int) -> FixtureSite:
    department = _LARGE_DEPARTMENTS[(index - 1) % len(_LARGE_DEPARTMENTS)]
    region = _LARGE_REGIONS[(index - 1) % len(_LARGE_REGIONS)]
    slug = f"large-{index:03d}"
    return FixtureSite(
        key=f"fixture-site-{slug}",
        name=f"{department} – {region} – Arbetsyta {index:03d}",
        resource_type="site",
        category="my_teams" if index % 5 == 0 else "other_sites",
        tree_profile="engineering" if index % 4 == 0 else "standard",
        url=f"https://sharepoint-fixture.invalid/sites/{slug}",
    )


LARGE_TENANT_SITES: tuple[FixtureSite, ...] = REPRESENTATIVE_SITES + tuple(
    _large_tenant_site(index) for index in range(1, 141)
)


STANDARD_TREE: tuple[FixtureTreeNode, ...] = (
    FixtureTreeNode(
        id="fixture-folder-governance",
        name="01 – Styrande dokument",
        item_type="folder",
        modified=_modified(2026, 8, 21, 14),
        children=(
            FixtureTreeNode(
                id="fixture-folder-policies",
                name="Policyer",
                item_type="folder",
                modified=_modified(2026, 8, 18),
                children=(
                    FixtureTreeNode(
                        id="fixture-file-information-security-policy",
                        name="Informationssäkerhetspolicy v3.2.pdf",
                        item_type="file",
                        modified=_modified(2026, 8, 18, 10),
                        size=2_842_711,
                    ),
                    FixtureTreeNode(
                        id="fixture-file-remote-work-policy",
                        name="Policy för distansarbete.docx",
                        item_type="file",
                        modified=_modified(2026, 6, 3, 16),
                        size=86_432,
                    ),
                ),
            ),
            FixtureTreeNode(
                id="fixture-folder-decisions",
                name="Beslut & protokoll",
                item_type="folder",
                modified=_modified(2026, 8, 20),
                children=(
                    FixtureTreeNode(
                        id="fixture-file-board-minutes",
                        name="Protokoll 2026-08-20 – justerat.pdf",
                        item_type="file",
                        modified=_modified(2026, 8, 20, 17),
                        size=734_118,
                    ),
                ),
            ),
        ),
    ),
    FixtureTreeNode(
        id="fixture-folder-projects",
        name="Projekt",
        item_type="folder",
        modified=_modified(2026, 8, 24),
        children=(
            FixtureTreeNode(
                id="fixture-folder-project-aurora",
                name="Aurora",
                item_type="folder",
                modified=_modified(2026, 8, 24, 13),
                children=(
                    FixtureTreeNode(
                        id="fixture-file-aurora-status",
                        name="Statusrapport – vecka 34.pptx",
                        item_type="file",
                        modified=_modified(2026, 8, 24, 13),
                        size=8_944_031,
                    ),
                    FixtureTreeNode(
                        id="fixture-file-aurora-risk-register",
                        name="Riskregister.xlsx",
                        item_type="file",
                        modified=_modified(2026, 8, 23, 9),
                        size=248_991,
                    ),
                ),
            ),
            FixtureTreeNode(
                id="fixture-folder-project-empty",
                name="Öresund – tom projektmapp",
                item_type="folder",
                modified=_modified(2026, 7, 1),
            ),
        ),
    ),
    FixtureTreeNode(
        id="fixture-folder-deep-level-1",
        name="Djupt nästlad struktur",
        item_type="folder",
        modified=_modified(2026, 5, 2),
        children=(
            FixtureTreeNode(
                id="fixture-folder-deep-level-2",
                name="Nivå 2",
                item_type="folder",
                modified=_modified(2026, 5, 2),
                children=(
                    FixtureTreeNode(
                        id="fixture-folder-deep-level-3",
                        name="Nivå 3 – åäö",
                        item_type="folder",
                        modified=_modified(2026, 5, 2),
                        children=(
                            FixtureTreeNode(
                                id="fixture-file-deep-readme",
                                name="README – längst ned.md",
                                item_type="file",
                                modified=_modified(2026, 5, 2),
                                size=1_024,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    FixtureTreeNode(
        id="fixture-folder-empty",
        name="Mallar",
        item_type="folder",
        modified=_modified(2025, 12, 31),
    ),
    FixtureTreeNode(
        id="fixture-file-welcome",
        name="Läs mig – start här.md",
        item_type="file",
        modified=_modified(2026, 8, 25, 7),
        size=1_247,
    ),
    FixtureTreeNode(
        id="fixture-file-business-plan",
        name="Verksamhetsplan 2026–2028.pdf",
        item_type="file",
        modified=_modified(2026, 8, 10, 11),
        size=4_718_592,
    ),
    FixtureTreeNode(
        id="fixture-file-zero-byte",
        name="Tom fil för gränsfall.txt",
        item_type="file",
        modified=_modified(2026, 8, 1),
        size=0,
    ),
    FixtureTreeNode(
        id="fixture-file-long-name",
        name="Uppföljning av verksamhetsmål och beslutade aktiviteter för tredje kvartalet 2026 – slutversion.docx",
        item_type="file",
        modified=_modified(2026, 8, 22, 15),
        size=49_807_361,
    ),
)


ENGINEERING_TREE: tuple[FixtureTreeNode, ...] = STANDARD_TREE + (
    FixtureTreeNode(
        id="fixture-folder-technical",
        name="Teknisk dokumentation",
        item_type="folder",
        modified=_modified(2026, 8, 25, 9),
        children=(
            FixtureTreeNode(
                id="fixture-file-architecture",
                name="Arkitekturöversikt.pdf",
                item_type="file",
                modified=_modified(2026, 8, 25, 9),
                size=12_583_044,
            ),
            FixtureTreeNode(
                id="fixture-file-api-export",
                name="API-export.json",
                item_type="file",
                modified=_modified(2026, 8, 24, 19),
                size=6_291_456,
            ),
            FixtureTreeNode(
                id="fixture-file-test-results",
                name="testresultat.csv",
                item_type="file",
                modified=_modified(2026, 8, 25, 6),
                size=318_221,
            ),
        ),
    ),
)


ONEDRIVE_TREE: tuple[FixtureTreeNode, ...] = (
    FixtureTreeNode(
        id="fixture-folder-onedrive-documents",
        name="Dokument",
        item_type="folder",
        modified=_modified(2026, 8, 25),
        children=(
            FixtureTreeNode(
                id="fixture-file-onedrive-notes",
                name="Anteckningar från workshop.docx",
                item_type="file",
                modified=_modified(2026, 8, 25, 12),
                size=128_491,
            ),
            FixtureTreeNode(
                id="fixture-file-onedrive-expenses",
                name="Utlägg augusti.xlsx",
                item_type="file",
                modified=_modified(2026, 8, 24, 16),
                size=76_104,
            ),
        ),
    ),
    FixtureTreeNode(
        id="fixture-folder-onedrive-shared",
        name="Delat med mig",
        item_type="folder",
        modified=_modified(2026, 8, 22),
        children=(
            FixtureTreeNode(
                id="fixture-file-onedrive-shared-presentation",
                name="Gemensam presentation – utkast.pptx",
                item_type="file",
                modified=_modified(2026, 8, 22, 14),
                size=18_276_902,
            ),
        ),
    ),
    FixtureTreeNode(
        id="fixture-folder-onedrive-empty",
        name="Personligt arkiv (tomt)",
        item_type="folder",
        modified=_modified(2026, 1, 1),
    ),
    FixtureTreeNode(
        id="fixture-file-onedrive-root",
        name="Snabblänkar.txt",
        item_type="file",
        modified=_modified(2026, 8, 25, 7),
        size=311,
    ),
)

EMPTY_TREE: tuple[FixtureTreeNode, ...] = ()


SITES_BY_SCENARIO: dict[SharePointFixtureScenario, tuple[FixtureSite, ...]] = {
    SharePointFixtureScenario.REPRESENTATIVE: REPRESENTATIVE_SITES,
    SharePointFixtureScenario.LARGE_TENANT: LARGE_TENANT_SITES,
    SharePointFixtureScenario.EMPTY: (),
}

TREE_BY_PROFILE: dict[FixtureTreeProfile, tuple[FixtureTreeNode, ...]] = {
    "standard": STANDARD_TREE,
    "engineering": ENGINEERING_TREE,
    "onedrive": ONEDRIVE_TREE,
    "empty": EMPTY_TREE,
}
