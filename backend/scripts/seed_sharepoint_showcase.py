"""Seed SharePoint knowledge at scale so the integration UI can be tried locally.

Creates four shared spaces (recreated on every run) holding the combinations
the knowledge UI must handle: a site imported as a 35-folder tree with every sync state and every
skip reason, a clean source with thousands of documents and long names, a
whole-site import under a second embedding model, and single items that
failed, never synced or sit in a OneDrive. One source goes into the
organization space and a failing one into the user's personal space. Change-notification
subscriptions are active, expired, failing or about to expire, and every
folder has weeks of sync history naming the files each sync changed.

``--simulate-sync`` then writes live progress for a few of those items to
Redis, the way a running sync does, so the progress UI can be watched without
a SharePoint tenant.

Runs only while SharePoint fixture mode is active (SHAREPOINT_FIXTURE_MODE_ENABLED
in a development environment), so it cannot write to a staging or production
database. Run it from backend/ inside the devcontainer:

    uv run python scripts/seed_sharepoint_showcase.py [--user EMAIL]
    uv run python scripts/seed_sharepoint_showcase.py --simulate-sync
    uv run python scripts/seed_sharepoint_showcase.py --remove
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import psycopg2
import psycopg2.extensions
import redis.asyncio as redis
from psycopg2.extras import (
    Json,
    execute_values,  # pyright: ignore[reportUnknownVariableType]  # psycopg2 stubs incomplete
)

from eneo.integration.domain.sync_progress import (
    IntegrationSyncProgress,
    IntegrationSyncProgressFile,
)
from eneo.integration.infrastructure.sharepoint_sync_progress import (
    SYNC_PROGRESS_TTL_SECONDS,
    sync_progress_key,
)
from eneo.main.config import Settings, get_settings
from eneo.redis.connection import build_redis_auth_kwargs, build_redis_url
from eneo.settings.encryption_service import EncryptionService

SPACE_ID = uuid.UUID("5a0e5a0e-0000-4000-8000-000000000001")
SECOND_SPACE_ID = uuid.UUID("5a0e5a0e-0000-4000-8000-000000000002")
SECOND_SPACE_NAME = "SharePoint – HR och nämnd"
# Shared spaces the seed creates.
SHARED_SPACES = {
    "main": (SPACE_ID, "SharePoint – storskaligt"),
    "second": (SECOND_SPACE_ID, SECOND_SPACE_NAME),
    "school": (
        uuid.UUID("5a0e5a0e-0000-4000-8000-000000000003"),
        "SharePoint – Utbildningsförvaltningen",
    ),
    "council": (
        uuid.UUID("5a0e5a0e-0000-4000-8000-000000000004"),
        "SharePoint – Kommunledningskontoret",
    ),
}
SPACE_NAME = "SharePoint – storskaligt"
# Every id the script creates is derived from this namespace, so a rerun
# replaces the same rows instead of piling up new ones.
NAMESPACE = uuid.UUID("5a0e5a0e-0000-4000-8000-0000000000ff")
SUBSCRIPTION_PREFIX = "showcase-"
TENANT_HOST = "https://contoso.sharepoint.com"
SHOWCASE_CLIENT_ID = "00000000-0000-4000-8000-5a0e5a0e0001"

CREDENTIALS_INVALID = (
    "SharePoint credentials are invalid or expired; an administrator must "
    "reconnect the integration"
)

# (reason, file extension, weight): the sync's own skip reasons, weighted the
# way a municipal document library tends to produce them.
SKIP_REASONS: list[tuple[str, str, int]] = [
    ("Unsupported file type (image)", ".jpg", 30),
    ("Unsupported file type (video)", ".mp4", 4),
    ("Unsupported file type (legacy Word .doc, save as .docx)", ".doc", 6),
    ("No text layer (scanned document; OCR is not supported)", ".pdf", 12),
    ("Empty or unreadable content", ".txt", 3),
    ("File too large (exceeds 50 MB limit)", ".pdf", 3),
    ("Exceeds extraction limit (500 PDF pages)", ".pdf", 2),
    ("Error: Incomplete download of '{name}' (1048576 of 4194304 bytes)", ".pdf", 2),
    ("Error: Password-protected file", ".xlsx", 3),
    ("Error: Corrupt or malformed file", ".docx", 2),
    ("Error: TimeoutError while extracting pdf", ".pdf", 1),
    ("Unsupported file type (OneNote)", ".one", 2),
    ("Error: HTTP 403 Forbidden", ".docx", 2),
    ("Error: SharePoint offers no download for this item", ".url", 1),
    ("Set aside after 3 failed attempts, tried again later: HTTP 500", ".pdf", 1),
    # Written by 2.2.x for unchanged files; shown as unchanged, never as a problem.
    ("Already synced (no changes)", ".docx", 2),
]
MAX_LISTED_SKIPPED = 50

DOCUMENT_WORDS = [
    "Protokoll",
    "Rutin",
    "Riktlinje",
    "Beslut",
    "Utredning",
    "Avtal",
    "Rapport",
    "Handlingsplan",
    "Kallelse",
    "Yttrande",
    "Delegationsbeslut",
    "Mall",
]
DOCUMENT_EXTENSIONS = [".pdf", ".docx", ".docx", ".pdf", ".xlsx", ".pptx", ".pdf"]


def sid(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


@dataclass
class Folder:
    """One imported integration knowledge item and the state it is seeded in."""

    key: str
    name: str
    folder_path: str | None
    url: str
    state: str  # ok | empty | never | error | credentials
    documents: int = 0
    skipped: int = 0
    error: str | None = None
    subfolders: list[str] = field(default_factory=lambda: list[str]())
    subscription: str | None = None
    selected_item_type: str = "folder"
    resource_type: str = "site"
    embedding: str = "primary"
    with_properties: bool = False


@dataclass
class Source:
    name: str
    site_id: str
    wrapper: bool
    folders: list[Folder]
    space: str = "main"  # a SHARED_SPACES key, "org" or "personal"


def site_folder(site: str, library: str, path: str) -> str:
    return f"{TENANT_HOST}/sites/{site}/{quote(library)}/{quote(path.strip('/'))}"


def build_sources(rng: random.Random) -> list[Source]:
    social_tree = {
        "Barn och unga": ["Utredningar", "Placeringar", "Familjehem", "Riktlinjer"],
        "Vuxen": ["Missbruk", "Ekonomiskt bistånd", "Boendestöd"],
        "Äldreomsorg": [
            "Hemtjänst",
            "Särskilt boende",
            "Biståndsbedömning",
            "Kvalitet och avvikelser",
        ],
        "Funktionsstöd": ["LSS-handläggning", "Daglig verksamhet"],
        "Rutiner": ["Dokumentation", "Sekretess", "Krisberedskap"],
        "Nämnd": ["Protokoll 2025", "Protokoll 2026", "Delegationsbeslut"],
        "Arkiv": [str(year) for year in range(2016, 2024)],
    }
    special = {
        "/Rutiner/Krisberedskap": ("never", None),
        "/Vuxen/Boendestöd": (
            "error",
            "Graph request failed: 504 Gateway Timeout after 3 retries",
        ),
        "/Arkiv/2019": (
            "error",
            "The folder was moved or deleted in SharePoint (itemNotFound)",
        ),
        "/Funktionsstöd/Daglig verksamhet": ("empty", None),
        "/Barn och unga/Familjehem": ("empty", None),
        "/Arkiv/2016": ("empty", None),
    }
    social: list[Folder] = []
    for top, children in social_tree.items():
        paths = [f"/{top}"] + [f"/{top}/{child}" for child in children]
        if top == "Nämnd":
            paths.append("/Nämnd/Protokoll 2026/Bilagor")
        for path in paths:
            state, error = special.get(path, ("ok", None))
            is_archive = path.startswith("/Arkiv/")
            documents = 0
            if state in ("ok", "error"):
                documents = rng.randint(180, 520) if is_archive else rng.randint(4, 160)
            skipped = rng.choice([0, 0, 2, 5, 12, 30, 75])
            if state == "empty":
                skipped = rng.randint(6, 40)
            if state == "never":
                skipped = 0
            social.append(
                Folder(
                    key=f"social{path}",
                    name=path.rsplit("/", 1)[-1],
                    folder_path=path,
                    url=site_folder("socialforvaltningen", "Delade dokument", path),
                    state=state,
                    documents=documents,
                    skipped=skipped,
                    error=error,
                    subfolders=["", "", "Mallar", "2026", "2026/Q3"],
                    # Archive folders sit in another drive whose watch keeps failing.
                    subscription="social-archive" if is_archive else "social",
                )
            )

    bygg_names = [
        "Bygglov – inkomna ansökningar med kompletteringar och grannyttranden 2026",
        "Detaljplaner under samråd",
        "Strandskyddsdispenser",
        "Tillsyn och olovligt byggande",
        "Mallar och checklistor för handläggare",
    ]
    bygg = [
        Folder(
            key=f"bygg/{name}",
            name=name,
            folder_path=f"/{name}",
            url=site_folder("stadsbyggnad", "Handlingar", name),
            state="ok",
            documents=2600 if index == 0 else rng.randint(20, 240),
            skipped=0 if index != 4 else 18,
            subfolders=["", "Ärenden/2026-01", "Ärenden/2026-02", "Ärenden/2026-03"],
            subscription="bygg",
            with_properties=True,
        )
        for index, name in enumerate(bygg_names)
    ]

    return [
        Source("Socialförvaltningen", "showcase-site-social", True, social),
        Source("Stadsbyggnad", "showcase-site-bygg", True, bygg),
        Source(
            "Intranätet",
            "showcase-site-intranat",
            False,
            [
                Folder(
                    key="intranat",
                    name="Intranätet",
                    folder_path=None,
                    url=f"{TENANT_HOST}/sites/intranat",
                    state="ok",
                    documents=1200,
                    skipped=64,
                    subfolders=[
                        "Delade dokument/Nyheter",
                        "Delade dokument/Personal",
                        "Delade dokument/IT",
                    ],
                    subscription="intranat",
                    selected_item_type="site_root",
                    embedding="secondary",
                )
            ],
        ),
        Source(
            "Projektdokument",
            "showcase-onedrive",
            False,
            [
                Folder(
                    key="onedrive",
                    name="Projektdokument",
                    folder_path="/Projekt/Eneo",
                    url="https://contoso-my.sharepoint.com/personal/demo_example_se/Documents/Projekt/Eneo",
                    state="ok",
                    documents=48,
                    skipped=3,
                    subfolders=["", "Underlag", "Möten"],
                    resource_type="onedrive",
                )
            ],
        ),
        Source(
            "HR-handboken",
            "showcase-site-hr",
            False,
            space="second",
            folders=[
                Folder(
                    key="hr",
                    name="HR-handboken",
                    folder_path="/Handbok",
                    url=site_folder("hr", "Delade dokument", "/Handbok"),
                    state="credentials",
                    documents=140,
                    error=CREDENTIALS_INVALID,
                    subfolders=["", "Lön", "Arbetsmiljö"],
                )
            ],
        ),
        Source(
            "Nämndhandlingar 2027",
            "showcase-site-namnd",
            False,
            space="second",
            folders=[
                Folder(
                    key="namnd2027",
                    name="Nämndhandlingar 2027",
                    folder_path="/2027",
                    url=site_folder("namnd", "Delade dokument", "/2027"),
                    state="never",
                )
            ],
        ),
        Source(
            "Mina anteckningar",
            "showcase-onedrive-personal",
            False,
            space="personal",
            folders=[
                Folder(
                    key="personal-notes",
                    name="Mina anteckningar",
                    folder_path="/Anteckningar",
                    url="https://contoso-my.sharepoint.com/personal/demo_example_se/Documents/Anteckningar",
                    state="error",
                    documents=12,
                    error="The folder was moved or deleted in OneDrive (itemNotFound)",
                    resource_type="onedrive",
                )
            ],
        ),
        Source(
            "Skolor",
            "showcase-site-skola",
            True,
            space="school",
            folders=[
                Folder(
                    key=f"skola/{name}",
                    name=name,
                    folder_path=f"/{name}",
                    url=site_folder("utbildning", "Delade dokument", f"/{name}"),
                    state=state,
                    documents=0
                    if state in ("never", "empty")
                    else rng.randint(30, 400),
                    skipped=rng.randint(10, 40)
                    if state == "empty"
                    else rng.choice([0, 3, 9]),
                    error=error,
                    subfolders=["", "Läsår 2025-26", "Läsår 2026-27"],
                    subscription="skola",
                )
                for name, state, error in [
                    ("Grundskola", "ok", None),
                    ("Gymnasium", "ok", None),
                    (
                        "Elevhälsa",
                        "error",
                        "Graph request failed: 503 Service Unavailable after 5 retries",
                    ),
                    ("Förskola", "empty", None),
                    ("Vuxenutbildning", "never", None),
                ]
            ],
        ),
        Source(
            "Styrdokument",
            "showcase-site-styrdokument",
            False,
            space="council",
            folders=[
                Folder(
                    key="styrdokument",
                    name="Styrdokument",
                    folder_path="/Styrdokument",
                    url=site_folder(
                        "kommunledning", "Delade dokument", "/Styrdokument"
                    ),
                    state="ok",
                    documents=320,
                    skipped=14,
                    subfolders=["", "Policyer", "Riktlinjer", "Planer"],
                    subscription="kommunledning",
                    with_properties=True,
                )
            ],
        ),
        Source(
            "Kommunfullmäktige",
            "showcase-site-kf",
            False,
            space="council",
            folders=[
                Folder(
                    key="kf",
                    name="Kommunfullmäktige",
                    folder_path="/Sammanträden",
                    url=site_folder(
                        "kommunledning", "Delade dokument", "/Sammanträden"
                    ),
                    state="credentials",
                    documents=410,
                    error=CREDENTIALS_INVALID,
                    subfolders=["", "2025", "2026"],
                )
            ],
        ),
        Source(
            "Gemensamma rutiner",
            "showcase-site-org",
            False,
            space="org",
            folders=[
                Folder(
                    key="org/rutiner",
                    name="Gemensamma rutiner",
                    folder_path="/Rutiner",
                    url=site_folder("intranat", "Delade dokument", "/Rutiner"),
                    state="ok",
                    documents=95,
                    skipped=7,
                    subfolders=["", "IT", "Säkerhet"],
                    subscription="intranat",
                )
            ],
        ),
    ]


def skipped_details(rng: random.Random, count: int) -> list[dict[str, str]]:
    reasons = [entry[:2] for entry in SKIP_REASONS]
    weights = [entry[2] for entry in SKIP_REASONS]
    details: list[dict[str, str]] = []
    for index in range(count):
        reason, extension = rng.choices(reasons, weights)[0]
        stem = f"{rng.choice(DOCUMENT_WORDS)} {index + 1:03d}"
        name = f"{stem}{extension}"
        details.append({"file": name, "reason": reason.format(name=name)})
    return details


def file_changes(
    rng: random.Random, kinds: list[tuple[str, int]]
) -> list[dict[str, str]]:
    """Named changes, e.g. [("added", 3), ("deleted", 1)], as a sync records them."""
    return [
        {
            "file": f"{rng.choice(DOCUMENT_WORDS)} {rng.randint(1, 9999):04d}"
            f"{rng.choice(DOCUMENT_EXTENSIONS)}",
            "change": change,
        }
        for change, count in kinds
        for _ in range(count)
    ]


def sync_metadata(
    *,
    trigger: str,
    processed: int,
    deleted: int,
    unchanged: int,
    skipped: list[dict[str, str]],
    changed: list[dict[str, str]] | None = None,
    reconcile_warning: str | None = None,
) -> dict[str, Any]:
    changed = changed or []
    metadata: dict[str, Any] = {
        "trigger": trigger,
        "files_processed": processed,
        "files_deleted": deleted,
        "pages_processed": 0,
        "folders_processed": 1,
        "unchanged_items": unchanged,
        "skipped_items": len(skipped),
        "skipped_total": len(skipped),
        "skipped_truncated": len(skipped) > MAX_LISTED_SKIPPED,
        "skipped_details": skipped[:MAX_LISTED_SKIPPED],
        "changed_details": changed[:MAX_LISTED_SKIPPED],
        "changed_total": len(changed),
        "changed_truncated": len(changed) > MAX_LISTED_SKIPPED,
    }
    if reconcile_warning:
        metadata["reconcile_warning"] = reconcile_warning
    return metadata


def guard(settings: Settings) -> None:
    if not settings.sharepoint_fixture_mode_active:
        sys.exit(
            "Refusing to run: SharePoint fixture mode is not active. Set "
            "SHAREPOINT_FIXTURE_MODE_ENABLED=true with ENVIRONMENT=development "
            "(local, dev or test) to seed showcase data."
        )


def connect(settings: Settings) -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        dbname=settings.postgres_db,
    )


def one(cur: psycopg2.extensions.cursor, query: str, *params: Any) -> Any:
    cur.execute(query, params)
    row = cur.fetchone()
    return row[0] if row else None


def remove_showcase(cur: psycopg2.extensions.cursor) -> None:
    spaces = [str(space_id) for space_id, _ in SHARED_SPACES.values()]
    # Items outside the seeded spaces (personal, organization) by their seeded ids.
    seeded = [
        str(sid(f"knowledge/{folder.key}"))
        for source in build_sources(random.Random(0))
        for folder in source.folders
    ]
    cur.execute(
        """SELECT id FROM integration_knowledge
           WHERE space_id = ANY(%s::uuid[]) OR id = ANY(%s::uuid[])""",
        (spaces, seeded),
    )
    ids = [row[0] for row in cur.fetchall()]
    if ids:
        cur.execute(
            "DELETE FROM info_blobs WHERE integration_knowledge_id = ANY(%s::uuid[])",
            (ids,),
        )
        cur.execute(
            "DELETE FROM sync_logs WHERE integration_knowledge_id = ANY(%s::uuid[])",
            (ids,),
        )
        cur.execute(
            "DELETE FROM integration_knowledge WHERE id = ANY(%s::uuid[])", (ids,)
        )
    cur.execute(
        "DELETE FROM sharepoint_subscriptions WHERE subscription_id LIKE %s",
        (f"{SUBSCRIPTION_PREFIX}%",),
    )
    for table in (
        "spaces_users",
        "spaces_embedding_models",
        "spaces_completion_models",
    ):
        cur.execute(f"DELETE FROM {table} WHERE space_id = ANY(%s::uuid[])", (spaces,))
    cur.execute("DELETE FROM spaces WHERE id = ANY(%s::uuid[])", (spaces,))


def remove_connection(cur: psycopg2.extensions.cursor) -> list[str]:
    """Delete the connection rows the seed creates when a tenant has none.

    Only rows with the seed's own ids go, and only while nothing else uses
    them: knowledge someone imported through the fake connection keeps it, a
    tenant app since given real credentials stays together with its
    connection and tenant integration, so SharePoint stays enabled, and a
    tenant integration that other connections hang off stays. Returns what
    was kept.
    """
    kept: list[str] = []
    app_id = str(sid("tenant-app"))
    if one(
        cur,
        "SELECT 1 FROM tenant_sharepoint_apps WHERE id = %s AND client_id <> %s",
        app_id,
        SHOWCASE_CLIENT_ID,
    ):
        kept.append(
            "the tenant SharePoint app, its connection and integration: the app "
            "now has real credentials"
        )
        return kept
    user_integration_id = str(sid("user-integration"))
    cur.execute(
        """DELETE FROM user_integrations
           WHERE id = %(id)s
             AND NOT EXISTS (SELECT 1 FROM integration_knowledge
                             WHERE user_integration_id = %(id)s)
             AND NOT EXISTS (SELECT 1 FROM sharepoint_subscriptions
                             WHERE user_integration_id = %(id)s)""",
        {"id": user_integration_id},
    )
    if not cur.rowcount and one(
        cur, "SELECT 1 FROM user_integrations WHERE id = %s", user_integration_id
    ):
        kept.append("the SharePoint connection, still used by imported knowledge")
    cur.execute(
        """DELETE FROM tenant_sharepoint_apps
           WHERE id = %(id)s AND client_id = %(client_id)s
             AND NOT EXISTS (SELECT 1 FROM user_integrations
                             WHERE tenant_app_id = %(id)s)""",
        {"id": app_id, "client_id": SHOWCASE_CLIENT_ID},
    )
    if not cur.rowcount and one(
        cur, "SELECT 1 FROM tenant_sharepoint_apps WHERE id = %s", app_id
    ):
        kept.append("the tenant SharePoint app, changed or still in use")
    tenant_integration_id = str(sid("tenant-integration"))
    cur.execute(
        """DELETE FROM tenant_integrations
           WHERE id = %(id)s
             AND NOT EXISTS (SELECT 1 FROM user_integrations
                             WHERE tenant_integration_id = %(id)s)""",
        {"id": tenant_integration_id},
    )
    if not cur.rowcount and one(
        cur, "SELECT 1 FROM tenant_integrations WHERE id = %s", tenant_integration_id
    ):
        kept.append("the tenant SharePoint integration, still used by connections")
    return kept


def resolve_user_integration(
    cur: psycopg2.extensions.cursor, settings: Settings, tenant_id: str, user_id: str
) -> str:
    """The tenant's organisation SharePoint connection, created when missing."""
    integration_id = one(
        cur, "SELECT id FROM integrations WHERE integration_type = 'sharepoint'"
    )
    if integration_id is None:
        sys.exit(
            "No SharePoint integration row; start the backend once so it is seeded."
        )
    tenant_integration_id = one(
        cur,
        "SELECT id FROM tenant_integrations WHERE tenant_id = %s AND integration_id = %s",
        tenant_id,
        integration_id,
    )
    if tenant_integration_id is None:
        tenant_integration_id = str(sid("tenant-integration"))
        cur.execute(
            "INSERT INTO tenant_integrations (id, tenant_id, integration_id) VALUES (%s, %s, %s)",
            (tenant_integration_id, tenant_id, integration_id),
        )
    app_id = one(
        cur, "SELECT id FROM tenant_sharepoint_apps WHERE tenant_id = %s", tenant_id
    )
    if app_id is None:
        app_id = str(sid("tenant-app"))
        secret = EncryptionService(settings).encrypt("showcase-client-secret")
        cur.execute(
            """INSERT INTO tenant_sharepoint_apps
                 (id, tenant_id, client_id, client_secret_encrypted, tenant_domain,
                  auth_method, created_by)
               VALUES (%s, %s, %s, %s, %s, 'tenant_app', %s)""",
            (
                app_id,
                tenant_id,
                SHOWCASE_CLIENT_ID,
                secret,
                "contoso.onmicrosoft.com",
                user_id,
            ),
        )
    user_integration_id = one(
        cur,
        """SELECT id FROM user_integrations
           WHERE tenant_id = %s AND tenant_integration_id = %s AND auth_type = 'tenant_app'""",
        tenant_id,
        tenant_integration_id,
    )
    if user_integration_id is None:
        user_integration_id = str(sid("user-integration"))
        cur.execute(
            """INSERT INTO user_integrations
                 (id, tenant_id, tenant_integration_id, authenticated, auth_type, tenant_app_id, user_id)
               VALUES (%s, %s, %s, true, 'tenant_app', %s, NULL)""",
            (user_integration_id, tenant_id, tenant_integration_id, app_id),
        )
    return str(user_integration_id)


def seed(settings: Settings, email: str) -> None:
    rng = random.Random(2026)
    now = datetime.now(timezone.utc)
    with connect(settings) as connection, connection.cursor() as cur:
        cur.execute(
            "SELECT id, tenant_id FROM users WHERE lower(email) = lower(%s) AND deleted_at IS NULL",
            (email,),
        )
        row = cur.fetchone()
        if row is None:
            sys.exit(f"No user {email!r}; pass --user with an existing email.")
        user_id, tenant_id = str(row[0]), str(row[1])
        org_space_id = one(
            cur,
            """SELECT id FROM spaces WHERE tenant_id = %s AND user_id IS NULL
               AND tenant_space_id IS NULL ORDER BY created_at LIMIT 1""",
            tenant_id,
        )
        cur.execute(
            """SELECT id FROM embedding_models
               WHERE deleted_at IS NULL AND (tenant_id = %s OR tenant_id IS NULL)
               ORDER BY (tenant_id IS NULL), is_default DESC NULLS LAST, name""",
            (tenant_id,),
        )
        models = [str(r[0]) for r in cur.fetchall()]
        if not models:
            sys.exit("No embedding model for the tenant; add one under Admin › Models.")
        embedding = {
            "primary": models[0],
            "secondary": models[1] if len(models) > 1 else models[0],
        }

        remove_showcase(cur)
        user_integration_id = resolve_user_integration(
            cur, settings, tenant_id, user_id
        )

        for space_id, space_name in SHARED_SPACES.values():
            cur.execute(
                """INSERT INTO spaces (id, name, description, tenant_id, user_id, tenant_space_id)
                   VALUES (%s, %s, %s, %s, NULL, %s)""",
                (
                    str(space_id),
                    space_name,
                    "SharePoint-kunskap för lokal test av gränssnittet",
                    tenant_id,
                    org_space_id,
                ),
            )
            cur.execute(
                "INSERT INTO spaces_users (space_id, user_id, role) VALUES (%s, %s, 'admin')",
                (str(space_id), user_id),
            )
            for model in set(embedding.values()):
                cur.execute(
                    "INSERT INTO spaces_embedding_models (space_id, embedding_model_id) VALUES (%s, %s)",
                    (str(space_id), model),
                )
        personal_space_id = one(
            cur,
            "SELECT id FROM spaces WHERE tenant_id = %s AND user_id = %s LIMIT 1",
            tenant_id,
            user_id,
        )
        space_ids: dict[str, str | None] = {
            key: str(space_id) for key, (space_id, _) in SHARED_SPACES.items()
        }
        space_ids["org"] = str(org_space_id) if org_space_id else None
        space_ids["personal"] = str(personal_space_id) if personal_space_id else None

        subscriptions = {
            "social": dict(expires=now + timedelta(days=2), failures=0),
            "social-archive": dict(
                expires=now - timedelta(days=3),
                failures=4,
                error="Subscription validation request failed: notification URL did not respond",
            ),
            "bygg": dict(expires=now + timedelta(days=2, hours=5), failures=0),
            "intranat": dict(
                expires=now + timedelta(hours=6),
                failures=1,
                error="Graph throttled the renewal (429); retried later",
            ),
            "skola": dict(expires=now + timedelta(days=20), failures=0),
            "kommunledning": dict(
                expires=now + timedelta(days=1, hours=2),
                failures=2,
                error="Microsoft Graph refused to reauthorize the subscription (403)",
            ),
        }
        subscription_ids: dict[str, str] = {}
        for key, sub in subscriptions.items():
            subscription_ids[key] = str(sid(f"subscription/{key}"))
            cur.execute(
                """INSERT INTO sharepoint_subscriptions
                     (id, user_integration_id, site_id, subscription_id, drive_id, expires_at,
                      consecutive_renewal_failures, last_renewal_failed_at, last_renewal_error,
                      last_webhook_received_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    subscription_ids[key],
                    user_integration_id,
                    f"showcase-site-{key}",
                    f"{SUBSCRIPTION_PREFIX}{key}",
                    f"showcase-drive-{key}",
                    sub["expires"],
                    sub["failures"],
                    now - timedelta(hours=8) if sub["failures"] else None,
                    sub.get("error"),
                    now - timedelta(minutes=rng.randint(5, 600)),
                ),
            )

        knowledge_count = 0
        document_count = 0
        log_count = 0
        for source in build_sources(rng):
            space_id = space_ids[source.space]
            if space_id is None:
                continue
            wrapper_id = str(sid(f"wrapper/{source.name}")) if source.wrapper else None
            for folder in source.folders:
                knowledge_id = str(sid(f"knowledge/{folder.key}"))
                knowledge_count += 1
                skipped = skipped_details(rng, folder.skipped)
                logs = history(rng, now, folder, skipped)
                log_count += len(logs)
                last_success = next(
                    (log["completed_at"] for log in logs if log["status"] == "success"),
                    None,
                )
                last_attempt = logs[0]["started_at"] if logs else None
                last_log = logs[0] if logs else None
                summary = None
                if last_log:
                    summary = {
                        key: last_log["metadata"].get(key, 0)
                        for key in (
                            "files_processed",
                            "files_deleted",
                            "skipped_items",
                            "unchanged_items",
                            "skipped_total",
                        )
                    }
                    summary["skipped_truncated"] = bool(
                        last_log["metadata"].get("skipped_truncated", False)
                    )
                documents = make_documents(
                    rng, now, folder, document_number=document_count
                )
                document_count += len(documents)
                cur.execute(
                    """INSERT INTO integration_knowledge
                         (id, name, original_name, url, space_id, embedding_model_id, tenant_id,
                          user_integration_id, size, site_id, drive_id, resource_type,
                          selected_item_type, folder_id, folder_path, wrapper_id, wrapper_name,
                          sharepoint_subscription_id, last_synced_at, last_sync_attempted_at,
                          last_sync_status, last_sync_error, last_sync_summary)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        knowledge_id,
                        folder.name,
                        folder.name,
                        folder.url,
                        space_id,
                        embedding[folder.embedding],
                        tenant_id,
                        user_integration_id,
                        sum(doc[2] for doc in documents),
                        source.site_id,
                        f"showcase-drive-{source.site_id}",
                        folder.resource_type,
                        folder.selected_item_type,
                        f"showcase-folder-{folder.key}" if folder.folder_path else None,
                        folder.folder_path,
                        wrapper_id,
                        source.name if source.wrapper else None,
                        subscription_ids.get(folder.subscription)
                        if folder.subscription
                        else None,
                        last_success,
                        last_attempt,
                        {"ok": "success", "empty": "success", "never": "never"}.get(
                            folder.state, "error"
                        ),
                        folder.error,
                        Json(summary) if summary else None,
                    ),
                )
                if documents:
                    execute_values(
                        cur,
                        """INSERT INTO info_blobs
                             (title, url, text, size, updated_at, created_at, source_metadata,
                              user_id, tenant_id, integration_knowledge_id, source_id,
                              version_state, embedding_model_id, sharepoint_item_id)
                           VALUES %s""",
                        [
                            (
                                title,
                                url,
                                f"{title}. Innehåll för lokal test av SharePoint-kunskap.",
                                size,
                                updated,
                                updated,
                                Json(properties) if properties else None,
                                user_id,
                                tenant_id,
                                knowledge_id,
                                str(uuid.uuid4()),
                                "active",
                                embedding[folder.embedding],
                                f"showcase-item-{folder.key}-{index}",
                            )
                            for index, (
                                title,
                                url,
                                size,
                                updated,
                                properties,
                            ) in enumerate(documents)
                        ],
                        page_size=1000,
                    )
                if logs:
                    execute_values(
                        cur,
                        # The API orders logs by created_at, so it must follow the run.
                        """INSERT INTO sync_logs
                             (integration_knowledge_id, sync_type, status, error_message,
                              sync_metadata, started_at, completed_at, created_at)
                           VALUES %s""",
                        [
                            (
                                knowledge_id,
                                log["sync_type"],
                                log["status"],
                                log["error"],
                                Json(log["metadata"]),
                                log["started_at"],
                                log["completed_at"],
                                log["started_at"],
                            )
                            for log in logs
                        ],
                    )
        connection.commit()
    names = ", ".join(repr(name) for _, name in SHARED_SPACES.values())
    print(
        f"Seeded {names}, the organization space and the personal space: "
        f"{knowledge_count} items, {document_count} documents, {log_count} sync logs."
    )
    print(f"Open /spaces/{SPACE_ID}/knowledge?tab=integrations")


def make_documents(
    rng: random.Random, now: datetime, folder: Folder, *, document_number: int
) -> list[tuple[str, str, int, datetime, list[dict[str, str]] | None]]:
    documents: list[tuple[str, str, int, datetime, list[dict[str, str]] | None]] = []
    for index in range(folder.documents):
        word = rng.choice(DOCUMENT_WORDS)
        title = (
            f"{word} {document_number + index + 1:05d}{rng.choice(DOCUMENT_EXTENSIONS)}"
        )
        subfolder = rng.choice(folder.subfolders or [""])
        base = folder.url.rstrip("/")
        if folder.selected_item_type == "site_root" and not subfolder:
            subfolder = "Delade dokument"
        path = "/".join(
            quote(part) for part in (subfolder.split("/") if subfolder else [])
        )
        url = f"{base}/{path + '/' if path else ''}{quote(title)}"
        properties = None
        if folder.with_properties:
            properties = [
                {
                    "name": "Diarienummer",
                    "label": "Diarienummer",
                    "value": f"SBN 2026-{rng.randint(100, 999)}",
                    "kind": "text",
                },
                {
                    "name": "Dokumenttyp",
                    "label": "Dokumenttyp",
                    "value": rng.choice(["Ansökan", "Beslut", "Yttrande", "Ritning"]),
                    "kind": "choice",
                },
            ]
        updated = now - timedelta(
            days=rng.randint(0, 400), minutes=rng.randint(0, 1440)
        )
        documents.append(
            (title, url, rng.randint(12_000, 4_800_000), updated, properties)
        )
    return documents


def history(
    rng: random.Random, now: datetime, folder: Folder, skipped: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Sync logs newest first; the newest one decides the folder's problems list."""
    if folder.state == "never":
        return []
    runs: list[dict[str, Any]] = []
    started = now - timedelta(days=45, hours=rng.randint(0, 12))
    runs.append(
        dict(
            sync_type="full",
            status="success",
            error=None,
            metadata=sync_metadata(
                trigger="manual",
                processed=folder.documents,
                deleted=0,
                unchanged=0,
                skipped=skipped,
                changed=file_changes(rng, [("added", folder.documents)]),
            ),
            started_at=started,
            completed_at=started + timedelta(seconds=30 + folder.documents // 2),
        )
    )
    moment = started
    while True:
        moment += timedelta(hours=rng.randint(10, 80))
        if moment > now - timedelta(hours=3):
            break
        processed = rng.choice([0, 0, 1, 1, 2, 3, 7])
        deleted = rng.choice([0, 0, 0, 1])
        added = rng.randint(0, processed)
        runs.append(
            dict(
                sync_type="delta",
                status="success",
                error=None,
                metadata=sync_metadata(
                    trigger="webhook",
                    processed=processed,
                    deleted=deleted,
                    unchanged=rng.randint(0, 3),
                    skipped=[],
                    changed=file_changes(
                        rng,
                        [
                            ("added", added),
                            ("updated", processed - added),
                            ("deleted", deleted),
                        ],
                    ),
                ),
                started_at=moment,
                completed_at=moment + timedelta(seconds=rng.randint(4, 50)),
            )
        )
    # A manual full sync last, so the problems list reflects every skipped file.
    final_start = now - timedelta(hours=rng.randint(1, 3), minutes=rng.randint(0, 59))
    final_processed = rng.randint(0, 6)
    final: dict[str, Any] = dict(
        sync_type="full",
        status="success",
        error=None,
        metadata=sync_metadata(
            trigger="manual",
            processed=final_processed,
            deleted=0,
            unchanged=max(0, folder.documents - 6),
            skipped=skipped,
            changed=file_changes(rng, [("updated", final_processed)]),
            reconcile_warning=(
                "Reconciliation skipped: would delete 40 of 57 indexed documents "
                "(above the safety cap)"
                if folder.key == "social/Arkiv/2018"
                else None
            ),
        ),
        started_at=final_start,
        completed_at=final_start + timedelta(minutes=2),
    )
    if folder.state in ("error", "credentials"):
        failing_since = now - timedelta(days=4 if folder.state == "credentials" else 1)
        runs = [run for run in runs if run["started_at"] < failing_since]
        for hours_ago in (2, 9, 26, 50, 90)[
            : 5 if folder.state == "credentials" else 3
        ]:
            attempt = now - timedelta(hours=hours_ago, minutes=rng.randint(0, 50))
            if attempt < failing_since:
                continue
            runs.append(
                dict(
                    sync_type=rng.choice(["delta", "full"]),
                    status="error",
                    error=folder.error,
                    metadata={"trigger": "webhook"},
                    started_at=attempt,
                    completed_at=attempt + timedelta(seconds=rng.randint(5, 70)),
                )
            )
    else:
        runs.append(final)
    return sorted(runs, key=lambda run: run["started_at"], reverse=True)


async def simulate_sync(settings: Settings) -> None:
    """Writes progress for four items for about a minute and a half, then clears it."""
    client = await redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        build_redis_url(settings),
        encoding="utf8",
        decode_responses=True,
        **build_redis_auth_kwargs(settings),
    )
    started = datetime.now(timezone.utc)
    full_onedrive = sid("knowledge/onedrive")
    deltas = [
        sid("knowledge/social/Barn och unga/Utredningar"),
        sid("knowledge/social/Äldreomsorg/Hemtjänst"),
    ]
    first_sync = sid("knowledge/namnd2027")

    def feed(
        stem: str, done: int, skipped_at: set[int], *, unchanged_upto: int = 0
    ) -> dict[str, Any]:
        """The file being read and the eight latest outcomes, as a sync reports them."""

        def name(number: int) -> str:
            return f"{stem} {number:03d}{'.png' if number in skipped_at else '.docx'}"

        recent = [
            IntegrationSyncProgressFile(
                name=name(number),
                outcome="skipped"
                if number in skipped_at
                else ("unchanged" if number <= unchanged_upto else "indexed"),
                reason="Unsupported file type (image)"
                if number in skipped_at
                else None,
            )
            for number in range(done, max(0, done - 8), -1)
        ]
        return {"current": name(done + 1), "recent": recent}

    async def write(knowledge_id: uuid.UUID, **values: Any) -> None:
        progress = IntegrationSyncProgress(
            integration_knowledge_id=knowledge_id,
            started_at=started,
            updated_at=datetime.now(timezone.utc),
            deleted=0,
            **values,
        )
        await client.set(
            sync_progress_key(knowledge_id),
            progress.model_dump_json(),
            ex=SYNC_PROGRESS_TTL_SECONDS,
        )

    try:
        for step in range(45):
            listed = min(48, 12 + step * 4)
            indexed = min(listed, step * 2)
            skipped_now = min(3, step // 12)
            await write(
                full_onedrive,
                sync_type="full",
                phase="discovering"
                if step < 2
                else ("finishing" if step > 40 else "processing"),
                total=None if step < 2 else listed,
                done=indexed + skipped_now,
                indexed=indexed,
                unchanged=0,
                skipped=skipped_now,
                **(
                    feed("Projektplan", indexed + skipped_now, {7, 19, 31})
                    if 2 <= step <= 40
                    else {}
                ),
            )
            for offset, knowledge_id in enumerate(deltas):
                if step < 30 + offset * 8:
                    await write(
                        knowledge_id,
                        sync_type="delta",
                        phase="processing",
                        total=None,
                        done=step // 3,
                        indexed=step // 4,
                        unchanged=step // 3 - step // 4,
                        skipped=0,
                        **feed(
                            "Utredning" if offset == 0 else "Hemtjänstrutin",
                            step // 3,
                            set(),
                            unchanged_upto=step // 3 - step // 4,
                        ),
                    )
                else:
                    await client.delete(sync_progress_key(knowledge_id))
            await write(
                first_sync,
                sync_type="full",
                phase="discovering" if step < 10 else "processing",
                total=None if step < 10 else 180 + step * 6,
                done=max(0, (step - 10) * 5),
                indexed=max(0, (step - 10) * 5),
                unchanged=0,
                skipped=0,
                **(feed("Nämndhandling", (step - 10) * 5, set()) if step >= 10 else {}),
            )
            await asyncio.sleep(2)
    finally:
        await client.delete(
            *[sync_progress_key(item) for item in (full_onedrive, first_sync, *deltas)]
        )
        await client.aclose()
    print("Simulated syncs finished; progress cleared.")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--user",
        help="Email of the user who becomes admin of the space (default: DEFAULT_USER_EMAIL)",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--remove",
        action="store_true",
        help="Delete the showcase spaces and the connection the seed created",
    )
    action.add_argument(
        "--simulate-sync",
        action="store_true",
        help="Write live sync progress for a few seeded items for about 90 seconds",
    )
    args = parser.parse_args()

    settings = get_settings()
    guard(settings)
    if args.simulate_sync:
        asyncio.run(simulate_sync(settings))
        return
    if args.remove:
        with connect(settings) as connection, connection.cursor() as cur:
            remove_showcase(cur)
            kept = remove_connection(cur)
            connection.commit()
        print("Removed the showcase spaces and the sources the seed placed elsewhere.")
        for row in kept:
            print(f"Kept {row}.")
        return
    email = args.user or getattr(settings, "default_user_email", None)
    if not email:
        sys.exit("Pass --user EMAIL or set DEFAULT_USER_EMAIL.")
    seed(settings, email)


if __name__ == "__main__":
    main()
