"""Deterministic data for validating the SharePoint import UI.

All identifiers use a ``fixture-`` prefix and all URLs use the reserved
``.invalid`` top-level domain. This makes accidental use outside the fixture
API visible and prevents test links from resolving to a real Microsoft tenant.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from eneo.info_blobs.info_blob import SourceMetadataEntry
from eneo.integration.sharepoint_fixture.models import SharePointFixtureScenario

FixtureCategory = Literal["my_teams", "other_sites", "onedrive"]
FixtureResourceType = Literal["site", "onedrive"]
FixtureTreeItemType = Literal["file", "folder"]
FixtureTreeProfile = Literal["standard", "engineering", "records", "onedrive", "empty"]


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
    # Library columns a real import would store, so the picker shows the same
    # thing in fixture mode as against a tenant. Only files carry them.
    source_metadata: tuple[SourceMetadataEntry, ...] = ()


def _properties(
    *,
    dokumenttyp: str | None = None,
    verksamhet: str | list[str] | None = None,
    giltig_till: str | None = None,
    extern: bool | None = None,
    innehallsansvarig_enhet: str | None = None,
) -> tuple[SourceMetadataEntry, ...]:
    """The column set of the fixture libraries, in the library's column order."""
    entries: list[SourceMetadataEntry] = []
    if dokumenttyp is not None:
        entries.append(
            SourceMetadataEntry(
                name="Dokumenttyp",
                label="Dokumenttyp",
                value=dokumenttyp,
                kind="choice",
            )
        )
    if verksamhet is not None:
        entries.append(
            SourceMetadataEntry(
                name="Verksamhet", label="Verksamhet", value=verksamhet, kind="choice"
            )
        )
    if giltig_till is not None:
        entries.append(
            SourceMetadataEntry(
                name="Giltig_x0020_till",
                label="Giltig till",
                value=f"{giltig_till}T00:00:00Z",
                kind="date",
            )
        )
    if extern is not None:
        entries.append(
            SourceMetadataEntry(
                name="Extern",
                label="Extern publicering",
                value="true" if extern else "false",
                kind="boolean",
            )
        )
    if innehallsansvarig_enhet is not None:
        entries.append(
            SourceMetadataEntry(
                name="Ansvarig_x0020_enhet",
                label="Ansvarig enhet",
                value=innehallsansvarig_enhet,
                kind="text",
            )
        )
    return tuple(entries)


def _modified(year: int, month: int, day: int, hour: int = 8) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


REPRESENTATIVE_SITES: tuple[FixtureSite, ...] = (
    FixtureSite(
        key="fixture-site-records-centre",
        name="Dokumentcenter – metadatatungt bibliotek",
        resource_type="site",
        category="my_teams",
        tree_profile="records",
        url="https://sharepoint-fixture.invalid/sites/records-centre",
    ),
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
                        source_metadata=_properties(
                            dokumenttyp="Policy",
                            verksamhet=["Informationssäkerhet", "Hela organisationen"],
                            giltig_till="2027-06-30",
                            extern=False,
                            innehallsansvarig_enhet="Informationssäkerhet och dataskydd",
                        ),
                    ),
                    FixtureTreeNode(
                        id="fixture-file-remote-work-policy",
                        name="Policy för distansarbete.docx",
                        item_type="file",
                        modified=_modified(2026, 6, 3, 16),
                        size=86_432,
                        source_metadata=_properties(
                            dokumenttyp="Policy",
                            verksamhet="HR",
                            giltig_till="2026-12-31",
                            extern=True,
                            innehallsansvarig_enhet="HR & People",
                        ),
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
                        source_metadata=_properties(
                            dokumenttyp="Protokoll", verksamhet="Ledning", extern=False
                        ),
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
                        source_metadata=_properties(
                            dokumenttyp="Statusrapport",
                            verksamhet=["Projekt Aurora", "Extern samverkan"],
                            extern=True,
                        ),
                    ),
                    FixtureTreeNode(
                        id="fixture-file-aurora-risk-register",
                        name="Riskregister.xlsx",
                        item_type="file",
                        modified=_modified(2026, 8, 23, 9),
                        size=248_991,
                        source_metadata=_properties(
                            dokumenttyp="Riskregister",
                            verksamhet="Projekt Aurora",
                            giltig_till="2026-10-31",
                            extern=False,
                        ),
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
        source_metadata=_properties(
            dokumenttyp="Verksamhetsplan",
            verksamhet="Hela organisationen",
            giltig_till="2028-12-31",
            extern=True,
            innehallsansvarig_enhet="Ledningsgrupp Sverige",
        ),
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
        source_metadata=_properties(
            dokumenttyp="Uppföljning",
            verksamhet=["Ekonomi", "Verksamhetsutveckling"],
            extern=False,
        ),
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
                source_metadata=_properties(
                    dokumenttyp="Teknisk dokumentation",
                    verksamhet="Produkt & utveckling",
                    extern=False,
                    innehallsansvarig_enhet="Arkitektur",
                ),
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
                source_metadata=_properties(
                    dokumenttyp="Testresultat", verksamhet="Produkt & utveckling"
                ),
            ),
        ),
    ),
)


def _records(
    *,
    dokumenttyp: str,
    status: str,
    sekretess: str = "Öppen",
    sprak: str = "Svenska",
    malgrupp: list[str] | None = None,
    omrade: str = "Socialtjänst",
    process: str = "Handläggning",
    region: str = "Hela kommunen",
    kanal: str = "Intranät",
    format_: str = "Word",
    arendetyp: str = "Rutinärende",
    nyckelord: list[str] | None = None,
    extern: bool = False,
    granskad: bool = True,
    arkiveras: bool = False,
    tillganglighetsanpassad: bool = True,
    version: str = "1.0",
    diarienummer: str = "KS 2026/0001",
    beslutad_av: str = "Kommunstyrelsen",
    lagrum: str = "SoL 4 kap. 1 §",
    giltig_fran: str = "2026-01-01",
    giltig_till: str = "2027-12-31",
    senast_granskad: str = "2026-06-01",
    nasta_granskning: str = "2027-06-01",
) -> tuple[SourceMetadataEntry, ...]:
    """A records-management library: 24 columns of mixed kinds, so the filter
    UI can be checked against a library wider than the picker was drawn for."""

    def choice(name: str, label: str, value: str | list[str]) -> SourceMetadataEntry:
        return SourceMetadataEntry(name=name, label=label, value=value, kind="choice")

    def yes_no(name: str, label: str, value: bool) -> SourceMetadataEntry:
        return SourceMetadataEntry(
            name=name, label=label, value="true" if value else "false", kind="boolean"
        )

    def text(name: str, label: str, value: str) -> SourceMetadataEntry:
        return SourceMetadataEntry(name=name, label=label, value=value, kind="text")

    def date(name: str, label: str, value: str) -> SourceMetadataEntry:
        return SourceMetadataEntry(
            name=name, label=label, value=f"{value}T00:00:00Z", kind="date"
        )

    return (
        choice("Dokumenttyp", "Dokumenttyp", dokumenttyp),
        choice("Status", "Status", status),
        choice("Sekretess", "Sekretess", sekretess),
        choice("Sprak", "Språk", sprak),
        choice("Malgrupp", "Målgrupp", malgrupp or ["Medarbetare"]),
        choice("Omrade", "Område", omrade),
        choice("Process", "Process", process),
        choice("Region", "Region", region),
        choice("Kanal", "Publiceringskanal", kanal),
        choice("Format", "Format", format_),
        choice("Arendetyp", "Ärendetyp", arendetyp),
        choice("Nyckelord", "Nyckelord", nyckelord or ["rutin"]),
        yes_no("Extern", "Extern publicering", extern),
        yes_no("Granskad", "Granskad", granskad),
        yes_no("Arkiveras", "Ska arkiveras", arkiveras),
        yes_no("Tillganglig", "Tillgänglighetsanpassad", tillganglighetsanpassad),
        text("Version_x0020_nr", "Versionsnummer", version),
        text("Diarienummer", "Diarienummer", diarienummer),
        text("Beslutad_x0020_av", "Beslutad av", beslutad_av),
        text("Lagrum", "Lagrum", lagrum),
        date("Giltig_x0020_fran", "Giltig från", giltig_fran),
        date("Giltig_x0020_till", "Giltig till", giltig_till),
        date("Senast_x0020_granskad", "Senast granskad", senast_granskad),
        date("Nasta_x0020_granskning", "Nästa granskning", nasta_granskning),
    )


RECORDS_TREE: tuple[FixtureTreeNode, ...] = (
    FixtureTreeNode(
        id="fixture-folder-records-routines",
        name="Rutiner",
        item_type="folder",
        modified=_modified(2026, 9, 2),
        children=(
            FixtureTreeNode(
                id="fixture-file-records-routine-home-care",
                name="Rutin för larm inom hemtjänsten.docx",
                item_type="file",
                modified=_modified(2026, 9, 2, 9),
                size=184_220,
                source_metadata=_records(
                    dokumenttyp="Rutin",
                    status="Gällande",
                    omrade="Äldreomsorg",
                    process="Hemtjänst",
                    malgrupp=["Medarbetare", "Chefer"],
                    nyckelord=["larm", "hemtjänst", "trygghet"],
                    diarienummer="SN 2026/0142",
                    beslutad_av="Socialnämnden",
                ),
            ),
            FixtureTreeNode(
                id="fixture-file-records-routine-medication",
                name="Rutin för läkemedelshantering.docx",
                item_type="file",
                modified=_modified(2026, 8, 18, 11),
                size=240_118,
                source_metadata=_records(
                    dokumenttyp="Rutin",
                    status="Under revidering",
                    sekretess="Intern",
                    omrade="Hälso- och sjukvård",
                    process="Läkemedel",
                    granskad=False,
                    nyckelord=["läkemedel", "delegering"],
                    diarienummer="SN 2025/0981",
                    beslutad_av="Medicinskt ansvarig sjuksköterska",
                    lagrum="HSLF-FS 2017:37",
                ),
            ),
            FixtureTreeNode(
                id="fixture-file-records-routine-english",
                name="Routine for incident reporting.pdf",
                item_type="file",
                modified=_modified(2026, 7, 30, 15),
                size=96_410,
                source_metadata=_records(
                    dokumenttyp="Rutin",
                    status="Gällande",
                    sprak="Engelska",
                    kanal="Extern webb",
                    format_="PDF",
                    extern=True,
                    malgrupp=["Medarbetare", "Leverantörer"],
                    nyckelord=["incident", "avvikelse"],
                    diarienummer="KS 2026/0310",
                ),
            ),
        ),
    ),
    FixtureTreeNode(
        id="fixture-folder-records-policies",
        name="Styrdokument",
        item_type="folder",
        modified=_modified(2026, 6, 12),
        children=(
            FixtureTreeNode(
                id="fixture-file-records-policy-data-protection",
                name="Dataskyddspolicy.pdf",
                item_type="file",
                modified=_modified(2026, 6, 12, 8),
                size=512_332,
                source_metadata=_records(
                    dokumenttyp="Policy",
                    status="Gällande",
                    sekretess="Öppen",
                    omrade="Hela organisationen",
                    process="Dataskydd",
                    kanal="Extern webb",
                    format_="PDF",
                    arendetyp="Styrande",
                    extern=True,
                    arkiveras=True,
                    nyckelord=["GDPR", "personuppgifter"],
                    diarienummer="KS 2024/1187",
                    lagrum="GDPR art. 5",
                    giltig_fran="2024-09-01",
                    giltig_till="2028-08-31",
                ),
            ),
            FixtureTreeNode(
                id="fixture-file-records-policy-archived",
                name="Riktlinje för distansarbete 2021 (upphävd).docx",
                item_type="file",
                modified=_modified(2024, 1, 10, 10),
                size=77_912,
                source_metadata=_records(
                    dokumenttyp="Riktlinje",
                    status="Upphävd",
                    omrade="HR",
                    process="Arbetsmiljö",
                    arendetyp="Styrande",
                    arkiveras=True,
                    tillganglighetsanpassad=False,
                    nyckelord=["distansarbete"],
                    diarienummer="KS 2021/0455",
                    version="2.3",
                    giltig_fran="2021-03-01",
                    giltig_till="2023-12-31",
                    senast_granskad="2023-11-15",
                    nasta_granskning="2023-11-15",
                ),
            ),
        ),
    ),
    FixtureTreeNode(
        id="fixture-file-records-minutes",
        name="Protokoll socialnämnden 2026-08-27.pdf",
        item_type="file",
        modified=_modified(2026, 8, 28, 9),
        size=1_204_551,
        source_metadata=_records(
            dokumenttyp="Protokoll",
            status="Gällande",
            sekretess="Delvis sekretess",
            omrade="Socialtjänst",
            process="Nämndadministration",
            kanal="Intranät",
            format_="PDF",
            arendetyp="Beslut",
            arkiveras=True,
            nyckelord=["protokoll", "socialnämnden"],
            diarienummer="SN 2026/0001",
            beslutad_av="Socialnämnden",
            lagrum="KL 5 kap.",
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
    "records": RECORDS_TREE,
    "onedrive": ONEDRIVE_TREE,
    "empty": EMPTY_TREE,
}
