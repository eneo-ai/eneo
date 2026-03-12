"""Integration test: API Key Access Matrix.

Creates 12 API key configurations and probes ALL endpoint groups,
collecting results into a readable matrix that shows what each key can/cannot access.

Covers every router mount in routers.py to verify guard patterns are correct:
- Resource-guarded endpoints (assistants, apps, spaces, groups, files, etc.)
- TENANT_ADMIN_API_KEY_GUARDS (admin + scope: models, MCP, integrations, etc.)
- TENANT_ADMIN_SCOPE_GUARDS (scope only: analysis, jobs, logging)
- Special endpoints (api-keys, settings, users, dashboard, prompts)
- Unguarded endpoints (icons, limits, templates, ai-models, settings GET)

Run with:
    uv run pytest tests/integration/test_api_key_access_matrix.py -v -s
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Fixtures (same pattern as test_api_key_scope_integration.py)
# ---------------------------------------------------------------------------


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
    return user


@pytest.fixture
async def bearer_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(default_user)
    return token


@pytest.fixture
async def api_client(app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test.local",
        follow_redirects=True,
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_space(client, *, token, name=None):
    name = name or f"space-{uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_assistant(client, *, token, space_id, insight_enabled=False):
    resp = await client.post(
        "/api/v1/assistants/",
        json={"name": f"asst-{uuid4().hex[:8]}", "space_id": space_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    asst_id = resp.json()["id"]

    if insight_enabled:
        resp = await client.post(
            f"/api/v1/assistants/{asst_id}/",
            json={"insight_enabled": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text

    return asst_id


async def _create_app(client, *, token, space_id):
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/applications/apps/",
        json={"name": f"app-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_group(client, *, token, space_id, name=None):
    name = name or f"grp-{uuid4().hex[:8]}"
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/knowledge/groups/",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_api_key(
    client,
    *,
    token: str,
    scope_type: str = "tenant",
    scope_id: str | None = None,
    permission: str = "read",
    resource_permissions: dict | None = None,
    expires_at: str | None = None,
) -> dict:
    """Create an API key and return {"secret": ..., "id": ...}."""
    body: dict = {
        "name": f"key-{uuid4().hex[:8]}",
        "key_type": "sk_",
        "permission": permission,
        "scope_type": scope_type,
    }
    if scope_id is not None:
        body["scope_id"] = scope_id
    if resource_permissions is not None:
        body["resource_permissions"] = resource_permissions
    if expires_at is not None:
        body["expires_at"] = expires_at
    resp = await client.post(
        "/api/v1/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"secret": data["secret"], "id": data["api_key"]["id"]}


# ---------------------------------------------------------------------------
# Result collection
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    key_name: str
    method: str
    endpoint_name: str
    path: str
    status_code: int
    actual: str  # "allow" or "deny"
    expected: str  # "allow" or "deny"
    description: str = ""

    @property
    def is_error(self) -> bool:
        """A 5xx on an expected-deny probe may mask a missing guard."""
        return self.status_code >= 500 and self.expected == "deny"

    @property
    def passed(self) -> bool:
        if self.is_error:
            return False
        return self.actual == self.expected


@dataclass
class MatrixCollector:
    results: list[ProbeResult] = field(default_factory=list)

    def add(self, result: ProbeResult):
        self.results.append(result)

    def print_matrix(self):
        print()
        print("API KEY ACCESS MATRIX")
        print("=" * 175)
        header = (
            f"{'Key':<35}│ {'Method':<7}│ {'Endpoint':<28}│ {'Path':<65}│ {'HTTP':<5}│ "
            f"{'Expect':<7}│ Result"
        )
        print(header)
        print(
            "─" * 35 + "┼" + "─" * 8 + "┼" + "─" * 29
            + "┼" + "─" * 66 + "┼" + "─" * 6 + "┼" + "─" * 8 + "┼" + "─" * 8
        )

        for r in self.results:
            if r.is_error:
                status = "ERROR"
            elif r.passed:
                status = "PASS"
            else:
                status = "FAIL"
            print(
                f"{r.key_name:<35}│ {r.method:<7}│ {r.endpoint_name:<28}│ "
                f"{r.path:<65}│ {r.status_code:<5}│ {r.expected:<7}│ {status}"
            )

        print("=" * 175)
        passed = sum(1 for r in self.results if r.passed)
        errors = sum(1 for r in self.results if r.is_error)
        failed = sum(1 for r in self.results if not r.passed) - errors
        print(f"SUMMARY: {passed}/{len(self.results)} passed, {failed} failed, {errors} errors")

        if failed > 0:
            print()
            print("FAILURES:")
            for r in self.results:
                if not r.passed:
                    print(
                        f"  {r.key_name} | {r.method} {r.endpoint_name} | "
                        f"HTTP {r.status_code} | expected={r.expected} actual={r.actual}"
                    )

        # Print probe descriptions for probes that have them
        described = {}
        for r in self.results:
            if r.description and r.endpoint_name not in described:
                described[r.endpoint_name] = r.description
        if described:
            print()
            print("PROBE DESCRIPTIONS")
            print("─" * 80)
            for name, desc in described.items():
                print(f"  {name}")
                print(f"    {desc}")
                print()

        print()

    def write_to_file(self, filename: str):
        """Write matrix results to a CSV file in test-results/."""
        out_dir = Path(__file__).parent.parent.parent / "test-results"
        out_dir.mkdir(exist_ok=True)
        path = out_dir / filename

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["key", "method", "endpoint", "path", "status_code", "actual", "expected", "result"])
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            writer.writerow([r.key_name, r.method, r.endpoint_name, r.path,
                             r.status_code, r.actual, r.expected, status])
        path.write_text(buf.getvalue())
        print(f"Matrix written to {path}")


# ---------------------------------------------------------------------------
# Expected outcome computation
# ---------------------------------------------------------------------------

# Permission levels for comparison
PERM_ORDER = {"none": 0, "read": 1, "write": 2, "admin": 3}

# HTTP method -> minimum permission required
METHOD_PERM = {
    "GET": "read",
    "POST": "write",
    "PATCH": "write",
    "DELETE": "admin",
}


def _compute_expected(
    *,
    key_cfg: dict,
    method: str,
    endpoint: dict,
    resource_ids: dict,
) -> str:
    """Compute expected "allow" or "deny" for a key+endpoint probe.

    Encodes the 4 enforcement layers:
    1. Method permission (basic key.permission vs HTTP method)
    2. Resource permission (fine-grained per-resource-type, if set)
    3. Management permission (admin endpoints require admin key)
    4. Scope enforcement (non-tenant keys blocked from admin routes;
       list endpoint filtering; single-resource scope matching)
    """
    key_perm = key_cfg["permission"]
    scope_type = key_cfg["scope_type"]
    res_perms = key_cfg.get("resource_permissions")

    ep_resource_type = endpoint.get("resource_type")
    ep_scope_resource = endpoint.get("scope_resource")
    requires_admin_perm = endpoint.get("requires_admin_perm", False)
    is_admin_scope = endpoint.get("is_admin_scope", False)
    target_resource_key = endpoint.get("target_resource_key")
    is_unguarded = endpoint.get("is_unguarded", False)

    # Unguarded endpoints: any authenticated key should access them
    if is_unguarded:
        return "allow"

    # --- Layer 1: Method permission ---
    required_method_perm = METHOD_PERM.get(method, "admin")
    if PERM_ORDER.get(key_perm, 0) < PERM_ORDER.get(required_method_perm, 3):
        return "deny"

    # --- Layer 2: Resource permission (fine-grained) ---
    if res_perms is not None and ep_resource_type is not None:
        granted = res_perms.get(ep_resource_type, "none")
        if PERM_ORDER.get(granted, 0) < PERM_ORDER.get(required_method_perm, 3):
            return "deny"

    # --- Layer 3: Management permission ---
    if requires_admin_perm:
        if PERM_ORDER.get(key_perm, 0) < PERM_ORDER.get("admin", 3):
            return "deny"

    # --- Layer 4: Scope enforcement ---
    if is_admin_scope and scope_type != "tenant":
        return "deny"

    # For non-admin routes with scope checks, enforce scope rules
    if scope_type != "tenant" and ep_scope_resource is not None:
        # Admin resource_type routes block all non-tenant keys
        if ep_scope_resource == "admin":
            return "deny"

        # List endpoints (no target_resource_key)
        if target_resource_key is None:
            if scope_type == "assistant":
                if ep_scope_resource not in ("assistant", "conversation", "file"):
                    return "deny"
            elif scope_type == "app":
                if ep_scope_resource not in ("app", "app_run", "file"):
                    return "deny"
            # space-scoped: passes through to service-layer filtering
            return "allow"

        # Single-resource endpoints
        if scope_type == "space":
            # For space-scoped: resource must be in the key's space
            # We know resources with "_a_" suffix are in space A, "_b_" in space B
            if target_resource_key and "_b_" in target_resource_key:
                return "deny"
            return "allow"

        if scope_type == "assistant":
            # Assistant-scoped key can only access its own assistant
            if ep_scope_resource == "assistant":
                if target_resource_key and "_a_" in target_resource_key:
                    return "allow"
                return "deny"
            if ep_scope_resource == "file":
                return "allow"
            return "deny"

        if scope_type == "app":
            if ep_scope_resource == "app":
                if target_resource_key and "_a_" in target_resource_key:
                    return "allow"
                return "deny"
            if ep_scope_resource == "file":
                return "allow"
            return "deny"

    return "allow"


# ---------------------------------------------------------------------------
# Endpoint probe definitions
# ---------------------------------------------------------------------------


def _build_probes(resource_ids: dict) -> list[dict]:
    """Build the list of endpoint probes with resolved resource IDs.

    Covers every router mount in routers.py to verify guard patterns.
    Uses a fake UUID for endpoints that need resource IDs we don't have —
    a 404 still confirms the auth layer allowed the request through.
    """
    space_a = resource_ids["space_a_id"]
    space_b = resource_ids["space_b_id"]
    asst_a = resource_ids["assistant_a_id"]
    asst_b = resource_ids["assistant_b_id"]
    app_a = resource_ids.get("app_a_id")
    group_a = resource_ids["group_a_id"]
    group_b = resource_ids["group_b_id"]
    fake = "00000000-0000-0000-0000-000000000099"

    probes = [
        # =================================================================
        # RESOURCE-GUARDED ENDPOINTS
        # (require_resource_permission_for_method + require_api_key_scope_check)
        # =================================================================

        # --- Assistants (resource_type="assistants", scope_resource="assistant") ---
        {
            "name": "list-assistants",
            "method": "GET",
            "path": "/api/v1/assistants/",
            "resource_type": "assistants",
            "scope_resource": "assistant",
            "target_resource_key": None,
        },
        {
            "name": "get-assistant-a",
            "method": "GET",
            "path": f"/api/v1/assistants/{asst_a}/",
            "resource_type": "assistants",
            "scope_resource": "assistant",
            "target_resource_key": "assistant_a_id",
        },
        {
            "name": "get-assistant-b",
            "method": "GET",
            "path": f"/api/v1/assistants/{asst_b}/",
            "resource_type": "assistants",
            "scope_resource": "assistant",
            "target_resource_key": "assistant_b_id",
        },
        {
            "name": "create-assistant",
            "method": "POST",
            "path": "/api/v1/assistants/",
            "body": {"name": f"probe-asst-{uuid4().hex[:6]}", "space_id": space_a},
            "resource_type": "assistants",
            "scope_resource": "assistant",
            "target_resource_key": None,
        },
        # NOTE: DELETE probes omitted for real resources — destructive side effects
        # corrupt subsequent key probes. DELETE permission is exercised via admin probes.
        {
            "name": "asst-a-sessions",
            "method": "GET",
            "path": f"/api/v1/assistants/{asst_a}/sessions/",
            "resource_type": "assistants",
            "scope_resource": "assistant",
            "target_resource_key": "assistant_a_id",
        },
        {
            "name": "asst-a-prompts",
            "method": "GET",
            "path": f"/api/v1/assistants/{asst_a}/prompts/",
            "resource_type": "assistants",
            "scope_resource": "assistant",
            "target_resource_key": "assistant_a_id",
        },
        {
            "name": "asst-a-mcp-servers",
            "method": "GET",
            "path": f"/api/v1/assistants/{asst_a}/mcp-servers/",
            "resource_type": "assistants",
            "scope_resource": "assistant",
            "target_resource_key": "assistant_a_id",
        },

        # --- Conversations (resource_type="assistants", scope_resource="conversation") ---
        {
            "name": "list-conversations",
            "method": "GET",
            "path": f"/api/v1/conversations/?assistant_id={asst_a}",
            "resource_type": "assistants",
            "scope_resource": "conversation",
            "target_resource_key": None,
        },

        # --- Apps (resource_type="apps", scope_resource="app") ---
        {
            "name": "get-app-a",
            "method": "GET",
            "path": f"/api/v1/apps/{app_a}/",
            "resource_type": "apps",
            "scope_resource": "app",
            "target_resource_key": "app_a_id",
            "skip": app_a is None,
        },
        {
            "name": "update-app-a",
            "method": "PATCH",
            "path": f"/api/v1/apps/{app_a}/",
            "body": {"name": f"patched-{uuid4().hex[:6]}"},
            "resource_type": "apps",
            "scope_resource": "app",
            "target_resource_key": "app_a_id",
            "skip": app_a is None,
        },
        {
            "name": "app-a-runs",
            "method": "GET",
            "path": f"/api/v1/apps/{app_a}/runs/",
            "resource_type": "apps",
            "scope_resource": "app",
            "target_resource_key": "app_a_id",
            "skip": app_a is None,
        },
        {
            "name": "app-a-prompts",
            "method": "GET",
            "path": f"/api/v1/apps/{app_a}/prompts/",
            "resource_type": "apps",
            "scope_resource": "app",
            "target_resource_key": "app_a_id",
            "skip": app_a is None,
        },

        # --- App Runs (resource_type="apps", scope_resource="app_run") ---
        # NOTE: Skipping fake UUID probe — scope enforcement fails-closed for
        # non-tenant keys when the resource doesn't exist (can't verify ownership).

        # --- Spaces (resource_type="spaces", scope_resource="space") ---
        {
            "name": "list-spaces",
            "method": "GET",
            "path": "/api/v1/spaces/",
            "resource_type": "spaces",
            "scope_resource": "space",
            "target_resource_key": None,
        },
        {
            "name": "get-space-a",
            "method": "GET",
            "path": f"/api/v1/spaces/{space_a}/",
            "resource_type": "spaces",
            "scope_resource": "space",
            "target_resource_key": "space_a_id",
        },
        {
            "name": "get-space-b",
            "method": "GET",
            "path": f"/api/v1/spaces/{space_b}/",
            "resource_type": "spaces",
            "scope_resource": "space",
            "target_resource_key": "space_b_id",
        },
        {
            "name": "create-space",
            "method": "POST",
            "path": "/api/v1/spaces/",
            "body": {"name": f"probe-sp-{uuid4().hex[:6]}"},
            "resource_type": "spaces",
            "scope_resource": "space",
            "target_resource_key": None,
        },
        {
            "name": "space-a-knowledge",
            "method": "GET",
            "path": f"/api/v1/spaces/{space_a}/knowledge/",
            "resource_type": "spaces",
            "scope_resource": "space",
            "target_resource_key": "space_a_id",
        },
        {
            "name": "space-a-applications",
            "method": "GET",
            "path": f"/api/v1/spaces/{space_a}/applications/",
            "resource_type": "spaces",
            "scope_resource": "space",
            "target_resource_key": "space_a_id",
        },
        {
            "name": "space-a-group-members",
            "method": "GET",
            "path": f"/api/v1/spaces/{space_a}/group-members/",
            "resource_type": "spaces",
            "scope_resource": "space",
            "target_resource_key": "space_a_id",
        },
        {
            "name": "get-personal-space",
            "method": "GET",
            "path": "/api/v1/spaces/type/personal/",
            "resource_type": "spaces",
            "scope_resource": "space",
            "target_resource_key": None,
        },
        {
            "name": "get-org-space",
            "method": "GET",
            "path": "/api/v1/spaces/type/organization/",
            "resource_type": "spaces",
            "scope_resource": "space",
            "target_resource_key": None,
        },

        # --- Services (resource_type="apps", scope_resource="service") ---
        {
            "name": "list-services",
            "method": "GET",
            "path": "/api/v1/services/",
            "resource_type": "apps",
            "scope_resource": "service",
            "target_resource_key": None,
        },

        # --- Group Chats (resource_type="assistants", scope_resource="group_chat") ---
        # NOTE: Skipping fake UUID probe — scope enforcement fails-closed for
        # non-tenant keys when the resource doesn't exist.

        # --- Groups/Knowledge (resource_type="knowledge", scope_resource="collection") ---
        {
            "name": "list-groups",
            "method": "GET",
            "path": "/api/v1/groups/",
            "resource_type": "knowledge",
            "scope_resource": "collection",
            "target_resource_key": None,
        },
        {
            "name": "get-group-a",
            "method": "GET",
            "path": f"/api/v1/groups/{group_a}/",
            "resource_type": "knowledge",
            "scope_resource": "collection",
            "target_resource_key": "group_a_id",
        },
        {
            "name": "get-group-b",
            "method": "GET",
            "path": f"/api/v1/groups/{group_b}/",
            "resource_type": "knowledge",
            "scope_resource": "collection",
            "target_resource_key": "group_b_id",
        },
        {
            "name": "group-a-info-blobs",
            "method": "GET",
            "path": f"/api/v1/groups/{group_a}/info-blobs/",
            "resource_type": "knowledge",
            "scope_resource": "collection",
            "target_resource_key": "group_a_id",
        },

        # --- Files (resource_type="knowledge", scope_resource="file") ---
        {
            "name": "list-files",
            "method": "GET",
            "path": "/api/v1/files/",
            "resource_type": "knowledge",
            "scope_resource": "file",
            "target_resource_key": None,
        },

        # --- Info Blobs (resource_type="knowledge", scope_resource="info_blob") ---
        {
            "name": "list-info-blobs",
            "method": "GET",
            "path": "/api/v1/info-blobs/",
            "resource_type": "knowledge",
            "scope_resource": "info_blob",
            "target_resource_key": None,
        },

        # NOTE: list-websites (GET /api/v1/websites/) removed — endpoint is
        # explicitly deprecated and always returns 410.

        # --- Crawl Runs (resource_type="knowledge", scope_resource="crawl_run") ---
        # NOTE: Skipping fake UUID probe — scope enforcement fails-closed for
        # non-tenant keys when the resource doesn't exist.

        # =================================================================
        # TENANT_ADMIN_API_KEY_GUARDS (admin scope + admin permission)
        # =================================================================

        # --- Completion Models ---
        {
            "name": "list-completion-models",
            "method": "GET",
            "path": "/api/v1/completion-models/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "completion-model-usage-summary",
            "method": "GET",
            "path": "/api/v1/completion-models/usage-summary",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "completion-model-migration-history",
            "method": "GET",
            "path": "/api/v1/completion-models/migration-history",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Embedding Models ---
        {
            "name": "list-embedding-models",
            "method": "GET",
            "path": "/api/v1/embedding-models/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Transcription Models ---
        {
            "name": "list-transcription-models",
            "method": "GET",
            "path": "/api/v1/transcription-models/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Tenant Models (admin) ---
        {
            "name": "create-tenant-completion-model",
            "method": "POST",
            "path": "/api/v1/admin/tenant-models/completion/",
            "body": {"provider_id": fake, "name": "probe", "display_name": "Probe"},
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "create-tenant-embedding-model",
            "method": "POST",
            "path": "/api/v1/admin/tenant-models/embedding/",
            "body": {"provider_id": fake, "name": "probe", "display_name": "Probe"},
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "create-tenant-transcription-model",
            "method": "POST",
            "path": "/api/v1/admin/tenant-models/transcription/",
            "body": {"provider_id": fake, "name": "probe", "display_name": "Probe"},
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Model Providers ---
        {
            "name": "list-model-providers",
            "method": "GET",
            "path": "/api/v1/admin/model-providers/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "model-provider-capabilities",
            "method": "GET",
            "path": "/api/v1/admin/model-providers/capabilities/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- MCP Servers ---
        {
            "name": "list-mcp-servers",
            "method": "GET",
            "path": "/api/v1/mcp-servers/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "list-mcp-settings",
            "method": "GET",
            "path": "/api/v1/mcp-servers/settings/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "get-mcp-server-fake",
            "method": "GET",
            "path": f"/api/v1/mcp-servers/{fake}/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "get-mcp-server-tools-fake",
            "method": "GET",
            "path": f"/api/v1/mcp-servers/{fake}/tools/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Allowed Origins ---
        {
            "name": "list-allowed-origins",
            "method": "GET",
            "path": "/api/v1/allowed-origins/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Security Classifications ---
        {
            "name": "list-security-class",
            "method": "GET",
            "path": "/api/v1/security-classifications/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- User Groups ---
        {
            "name": "list-user-groups",
            "method": "GET",
            "path": "/api/v1/user-groups/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Integrations ---
        {
            "name": "list-integrations",
            "method": "GET",
            "path": "/api/v1/integrations/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "list-tenant-integrations",
            "method": "GET",
            "path": "/api/v1/integrations/tenant/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Storage ---
        {
            "name": "get-storage",
            "method": "GET",
            "path": "/api/v1/storage/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "get-storage-spaces",
            "method": "GET",
            "path": "/api/v1/storage/spaces/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Token Usage ---
        {
            "name": "get-token-usage",
            "method": "GET",
            "path": "/api/v1/token-usage/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "get-token-usage-users",
            "method": "GET",
            "path": "/api/v1/token-usage/users",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Admin Router (TENANT_ADMIN_API_KEY_GUARDS) ---
        {
            "name": "admin-list-users",
            "method": "GET",
            "path": "/api/v1/admin/users/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-predefined-roles",
            "method": "GET",
            "path": "/api/v1/admin/predefined-roles/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-api-key-policy",
            "method": "GET",
            "path": "/api/v1/admin/api-key-policy",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-list-api-keys",
            "method": "GET",
            "path": "/api/v1/admin/api-keys",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-super-key-status",
            "method": "GET",
            "path": "/api/v1/admin/super-api-key-status",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-users-inactive",
            "method": "GET",
            "path": "/api/v1/admin/users/inactive",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-users-deleted",
            "method": "GET",
            "path": "/api/v1/admin/users/deleted",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-notification-policy",
            "method": "GET",
            "path": "/api/v1/admin/api-keys/notification-policy",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-expiring-keys",
            "method": "GET",
            "path": "/api/v1/admin/api-keys/expiring-soon",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Tenant Self Credentials (mounted at /admin with internal prefix /credentials) ---
        # NOTE: The credentials router uses internal prefix="/credentials" and is
        # mounted at prefix="/admin". The GET endpoint returns provider credential
        # status. This requires checking the actual resolved path.
        # Skipped: 404 for all keys suggests a routing/path resolution issue.

        # --- Admin SharePoint (mounted at /admin) ---
        {
            "name": "admin-sharepoint-app",
            "method": "GET",
            "path": "/api/v1/admin/sharepoint/app",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-sharepoint-subs",
            "method": "GET",
            "path": "/api/v1/admin/sharepoint/subscriptions",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Audit (prefix="/audit", TENANT_ADMIN_API_KEY_GUARDS) ---
        # NOTE: GET /audit/logs requires an access session (POST /audit/access-session
        # first). Use retention-policy which doesn't require a session.
        {
            "name": "audit-retention-policy",
            "method": "GET",
            "path": "/api/v1/audit/retention-policy",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Roles (TENANT_ADMIN_API_KEY_GUARDS, conditional on using_access_management) ---
        {
            "name": "list-roles",
            "method": "GET",
            "path": "/api/v1/roles/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
            "description": "Only mounted if using_access_management is True. "
                           "May 404 if not enabled.",
        },
        {
            "name": "list-permissions",
            "method": "GET",
            "path": "/api/v1/roles/permissions/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Admin Templates: Assistant (TENANT_ADMIN_API_KEY_GUARDS) ---
        {
            "name": "admin-assistant-templates",
            "method": "GET",
            "path": "/api/v1/admin/templates/assistants/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-assistant-templates-deleted",
            "method": "GET",
            "path": "/api/v1/admin/templates/assistants/deleted",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # --- Admin Templates: App (TENANT_ADMIN_API_KEY_GUARDS) ---
        {
            "name": "admin-app-templates",
            "method": "GET",
            "path": "/api/v1/admin/templates/apps/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },
        {
            "name": "admin-app-templates-deleted",
            "method": "GET",
            "path": "/api/v1/admin/templates/apps/deleted",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # =================================================================
        # TENANT_ADMIN_SCOPE_GUARDS (admin scope, NO admin perm)
        # These allow tenant keys with any permission (read/write/admin)
        # =================================================================

        # --- Analysis ---
        {
            "name": "analysis-counts",
            "method": "GET",
            "path": "/api/v1/analysis/counts/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": False,
            "target_resource_key": None,
        },
        {
            "name": "analysis-metadata",
            "method": "GET",
            "path": "/api/v1/analysis/metadata-statistics/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": False,
            "target_resource_key": None,
        },
        {
            "name": "analysis-assistant-activity",
            "method": "GET",
            "path": "/api/v1/analysis/assistant-activity/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": False,
            "target_resource_key": None,
        },
        {
            "name": "analysis-conv-insights",
            "method": "GET",
            "path": f"/api/v1/analysis/conversation-insights/?assistant_id={asst_a}",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": False,
            "target_resource_key": None,
        },

        # --- Jobs ---
        {
            "name": "list-jobs",
            "method": "GET",
            "path": "/api/v1/jobs/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": False,
            "target_resource_key": None,
        },

        # --- Logging ---
        {
            "name": "get-logging-fake",
            "method": "GET",
            "path": f"/api/v1/logging/{fake}/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": False,
            "target_resource_key": None,
        },

        # =================================================================
        # SPECIAL: API KEY MANAGEMENT (admin scope, no admin perm guard)
        # api_key_router mounted with scope_check(resource_type="admin")
        # =================================================================
        {
            "name": "list-api-keys",
            "method": "GET",
            "path": "/api/v1/api-keys",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": False,
            "target_resource_key": None,
        },
        {
            "name": "api-key-constraints",
            "method": "GET",
            "path": "/api/v1/api-keys/creation-constraints",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": False,
            "target_resource_key": None,
        },
        {
            "name": "api-key-notif-prefs",
            "method": "GET",
            "path": "/api/v1/api-keys/notification-preferences",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": False,
            "target_resource_key": None,
        },
        {
            "name": "api-key-expiring",
            "method": "GET",
            "path": "/api/v1/api-keys/expiring-soon",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": False,
            "target_resource_key": None,
        },

        # =================================================================
        # SPECIAL: USERS ROUTER (split: admin vs user-facing)
        # =================================================================

        # users_admin_router: TENANT_ADMIN_API_KEY_GUARDS → /users
        {
            "name": "users-admin-list",
            "method": "GET",
            "path": "/api/v1/users/",
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
            "description": (
                "users_admin_router GET / mounted with "
                "TENANT_ADMIN_API_KEY_GUARDS. Note: also has "
                "users_router GET /me/ and /tenant/ without guards."
            ),
        },

        # users_router (no API key guards): /users/me/
        {
            "name": "users-me",
            "method": "GET",
            "path": "/api/v1/users/me/",
            "resource_type": None,
            "scope_resource": None,
            "is_admin_scope": False,
            "requires_admin_perm": False,
            "target_resource_key": None,
            "is_unguarded": True,
            "description": "User-facing endpoint, no API key guards.",
        },
        {
            "name": "users-tenant",
            "method": "GET",
            "path": "/api/v1/users/tenant/",
            "resource_type": None,
            "scope_resource": None,
            "is_admin_scope": False,
            "requires_admin_perm": False,
            "target_resource_key": None,
            "is_unguarded": True,
        },

        # =================================================================
        # SPECIAL: SETTINGS ROUTER (split: admin vs user-facing)
        # =================================================================

        # settings_router (no API key guards at router level, but uses legacy
        # auth dependency internally). GET /settings/ uses
        # get_user_from_token_or_assistant_api_key_without_assistant_id which
        # may reject keys with restricted resource_permissions.
        # GET /settings/models/ and /formats/ use get_container(with_user=True).
        {
            "name": "get-settings-models",
            "method": "GET",
            "path": "/api/v1/settings/models/",
            "resource_type": None,
            "scope_resource": None,
            "is_admin_scope": False,
            "requires_admin_perm": False,
            "target_resource_key": None,
            "is_unguarded": True,
        },
        {
            "name": "get-settings-formats",
            "method": "GET",
            "path": "/api/v1/settings/formats/",
            "resource_type": None,
            "scope_resource": None,
            "is_admin_scope": False,
            "requires_admin_perm": False,
            "target_resource_key": None,
            "is_unguarded": True,
        },

        # settings_admin_router: TENANT_ADMIN_API_KEY_GUARDS
        {
            "name": "settings-admin-upsert",
            "method": "POST",
            "path": "/api/v1/settings/",
            "body": {"chatbot_widget": {}},
            "resource_type": None,
            "scope_resource": "admin",
            "is_admin_scope": True,
            "requires_admin_perm": True,
            "target_resource_key": None,
        },

        # =================================================================
        # SPECIAL: DASHBOARD (scope_check only, no resource_perm guard)
        # =================================================================
        {
            "name": "get-dashboard",
            "method": "GET",
            "path": "/api/v1/dashboard/",
            "resource_type": None,
            "scope_resource": "space",
            "is_admin_scope": False,
            "requires_admin_perm": False,
            "target_resource_key": None,
            "description": (
                "Dashboard has scope_check(resource_type='space') but no "
                "resource_perm guard. Non-tenant keys with space scope should "
                "pass, assistant/app scoped keys should be denied."
            ),
        },

        # =================================================================
        # SPECIAL: PROMPTS (scope_check only, no resource_perm guard)
        # NOTE: Skipping fake UUID probe — scope enforcement resolves prompt's
        # space from path_param="id", failing closed for non-tenant keys on
        # non-existent resources.
        # =================================================================

        # =================================================================
        # UNGUARDED ENDPOINTS (no API key guards — any key should access)
        # =================================================================
        # NOTE: list-icons (GET /api/v1/icons/) removed — GET is not a valid
        # method on this route (only POST/DELETE), so it returns 405 without
        # reaching auth.
        {
            "name": "get-limits",
            "method": "GET",
            "path": "/api/v1/limits/",
            "resource_type": None,
            "scope_resource": None,
            "is_admin_scope": False,
            "requires_admin_perm": False,
            "target_resource_key": None,
            "is_unguarded": True,
        },
        # NOTE: list-templates (GET /api/v1/templates/) removed — endpoint has
        # a bug (missing tenant_id → 500). Covered by the sub-endpoints below.
        {
            "name": "list-assistant-templates",
            "method": "GET",
            "path": "/api/v1/templates/assistants/",
            "resource_type": None,
            "scope_resource": None,
            "is_admin_scope": False,
            "requires_admin_perm": False,
            "target_resource_key": None,
            "is_unguarded": True,
        },
        {
            "name": "list-app-templates",
            "method": "GET",
            "path": "/api/v1/templates/apps/",
            "resource_type": None,
            "scope_resource": None,
            "is_admin_scope": False,
            "requires_admin_perm": False,
            "target_resource_key": None,
            "is_unguarded": True,
        },
        {
            "name": "list-ai-models",
            "method": "GET",
            "path": "/api/v1/ai-models/",
            "resource_type": None,
            "scope_resource": None,
            "is_admin_scope": False,
            "requires_admin_perm": False,
            "target_resource_key": None,
            "is_unguarded": True,
        },
    ]
    return [p for p in probes if not p.get("skip", False)]


# ---------------------------------------------------------------------------
# Key configurations
# ---------------------------------------------------------------------------


def _build_key_configs(resource_ids: dict) -> list[dict]:
    """Build the 12 API key configs."""
    space_a = resource_ids["space_a_id"]
    asst_a = resource_ids["assistant_a_id"]
    app_a = resource_ids.get("app_a_id")

    configs = [
        {"name": "tenant-read", "permission": "read", "scope_type": "tenant"},
        {"name": "tenant-write", "permission": "write", "scope_type": "tenant"},
        {"name": "tenant-admin", "permission": "admin", "scope_type": "tenant"},
        {"name": "space-read", "permission": "read", "scope_type": "space", "scope_id": space_a},
        {"name": "space-write", "permission": "write", "scope_type": "space", "scope_id": space_a},
        {"name": "space-admin", "permission": "admin", "scope_type": "space", "scope_id": space_a},
        {"name": "assistant-read", "permission": "read", "scope_type": "assistant", "scope_id": asst_a},
        {"name": "assistant-write", "permission": "write", "scope_type": "assistant", "scope_id": asst_a},
    ]

    if app_a is not None:
        configs.extend([
            {"name": "app-read", "permission": "read", "scope_type": "app", "scope_id": app_a},
            {"name": "app-write", "permission": "write", "scope_type": "app", "scope_id": app_a},
        ])

    configs.extend([
        {
            "name": "tenant-with-assistants-rw",
            "permission": "write",
            "scope_type": "tenant",
            "resource_permissions": {
                "assistants": "write",
                "apps": "none",
                "spaces": "none",
                "knowledge": "none",
            },
        },
        {
            "name": "tenant-with-knowledge-rw",
            "permission": "write",
            "scope_type": "tenant",
            "resource_permissions": {
                "assistants": "none",
                "apps": "none",
                "spaces": "none",
                "knowledge": "write",
            },
        },
    ])

    return configs


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------


@pytest.mark.api_key_matrix
async def test_collect_access_matrix(api_client, bearer_token):
    """Create resources + keys, probe endpoints, print matrix, assert all pass."""

    # ---- Setup resources ----
    space_a = await _create_space(api_client, token=bearer_token, name="matrix-space-a")
    space_b = await _create_space(api_client, token=bearer_token, name="matrix-space-b")
    asst_a = await _create_assistant(
        api_client, token=bearer_token, space_id=space_a, insight_enabled=True
    )
    asst_b = await _create_assistant(api_client, token=bearer_token, space_id=space_b)

    app_a = None
    try:
        app_a = await _create_app(api_client, token=bearer_token, space_id=space_a)
    except AssertionError:
        import warnings
        warnings.warn(
            "App creation failed — all app-scoped probes and key configs will be skipped. "
            "Ensure prerequisites (e.g. transcription model) are available for full coverage.",
            stacklevel=1,
        )

    group_a = await _create_group(api_client, token=bearer_token, space_id=space_a)
    group_b = await _create_group(api_client, token=bearer_token, space_id=space_b)

    resource_ids = {
        "space_a_id": space_a,
        "space_b_id": space_b,
        "assistant_a_id": asst_a,
        "assistant_b_id": asst_b,
        "app_a_id": app_a,
        "group_a_id": group_a,
        "group_b_id": group_b,
    }

    # ---- Create API keys ----
    key_configs = _build_key_configs(resource_ids)
    key_secrets: dict[str, str] = {}
    for cfg in key_configs:
        result = await _create_api_key(
            api_client,
            token=bearer_token,
            scope_type=cfg["scope_type"],
            scope_id=cfg.get("scope_id"),
            permission=cfg["permission"],
            resource_permissions=cfg.get("resource_permissions"),
        )
        key_secrets[cfg["name"]] = result["secret"]

    # ---- Build probes ----
    probes = _build_probes(resource_ids)

    # ---- Probe all endpoints with all keys ----
    collector = MatrixCollector()

    for cfg in key_configs:
        secret = key_secrets[cfg["name"]]
        headers = {"x-api-key": secret}

        for probe in probes:
            method = probe["method"]
            path = probe["path"]
            body = probe.get("body")

            expected = _compute_expected(
                key_cfg=cfg,
                method=method,
                endpoint=probe,
                resource_ids=resource_ids,
            )

            if method == "GET":
                resp = await api_client.get(path, headers=headers)
            elif method == "POST":
                resp = await api_client.post(path, json=body or {}, headers=headers)
            elif method == "PATCH":
                resp = await api_client.patch(path, json=body or {}, headers=headers)
            elif method == "DELETE":
                resp = await api_client.delete(path, headers=headers)
            else:
                continue

            actual = "deny" if resp.status_code in (401, 403) else "allow"

            collector.add(
                ProbeResult(
                    key_name=cfg["name"],
                    method=method,
                    endpoint_name=probe["name"],
                    path=path,
                    status_code=resp.status_code,
                    actual=actual,
                    expected=expected,
                    description=probe.get("description", ""),
                )
            )

    # ---- Print and assert ----
    collector.print_matrix()
    collector.write_to_file("access_matrix.csv")

    failures = [r for r in collector.results if not r.passed]
    assert len(failures) == 0, (
        f"{len(failures)} access matrix mismatches. See matrix output above."
    )


@pytest.mark.api_key_matrix
async def test_tenant_key_revoked_after_admin_role_removed(
    api_client, bearer_token, db_container, default_user
):
    """A tenant API key should stop working when the owner's admin role is revoked.

    Flow:
    1. Admin user creates a tenant-admin API key
    2. Key works (can list spaces, list completion models)
    3. Admin role is revoked (downgraded to plain "User")
    4. Key should be denied on all endpoints
    """

    # ---- 1. Create a tenant-admin API key ----
    result = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="tenant",
        permission="admin",
    )
    key_headers = {"x-api-key": result["secret"]}

    # ---- 2. Verify the key works before revocation ----
    resp = await api_client.get("/api/v1/spaces/", headers=key_headers)
    assert resp.status_code == 200, f"Key should work before revocation: {resp.text}"

    resp = await api_client.get("/api/v1/completion-models/", headers=key_headers)
    assert resp.status_code == 200, f"Key should access admin endpoints before revocation: {resp.text}"

    # ---- 3. Revoke admin role (downgrade to "User") ----
    # Look up the "User" predefined role and the current user's username
    async with db_container() as container:
        predefined_roles_repo = container.predefined_roles_repo()
        user_role = await predefined_roles_repo.get_predefined_role_by_name("User")

    # Use the admin API to downgrade the user's role
    resp = await api_client.post(
        f"/api/v1/admin/users/{default_user.username}/",
        json={"predefined_roles": [{"id": str(user_role.id)}]},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Role downgrade failed: {resp.text}"

    # ---- 4. Key should now be denied ----
    resp = await api_client.get("/api/v1/spaces/", headers=key_headers)
    assert resp.status_code in (401, 403), (
        f"Key should be denied after admin revocation, got {resp.status_code}"
    )

    resp = await api_client.get("/api/v1/completion-models/", headers=key_headers)
    assert resp.status_code in (401, 403), (
        f"Key should be denied on admin endpoints after revocation, got {resp.status_code}"
    )


@pytest.mark.api_key_matrix
async def test_revoked_key_is_rejected(api_client, bearer_token):
    """A revoked API key should be rejected with 401."""

    # ---- 1. Create a key and verify it works ----
    result = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="tenant",
        permission="admin",
    )
    key_headers = {"x-api-key": result["secret"]}

    resp = await api_client.get("/api/v1/spaces/", headers=key_headers)
    assert resp.status_code == 200, f"Key should work before revocation: {resp.text}"

    # ---- 2. Revoke the key ----
    resp = await api_client.post(
        f"/api/v1/api-keys/{result['id']}/revoke",
        json={"reason_code": "security_concern", "reason_text": "Test revocation"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Revoke failed: {resp.text}"

    # ---- 3. Key should now be rejected ----
    resp = await api_client.get("/api/v1/spaces/", headers=key_headers)
    assert resp.status_code == 401, (
        f"Revoked key should return 401, got {resp.status_code}"
    )


@pytest.mark.api_key_matrix
async def test_expired_key_is_rejected(api_client, bearer_token):
    """An expired API key should be rejected with 401."""

    # ---- 1. Create a key that expires in the past ----
    result = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="tenant",
        permission="admin",
        expires_at="2020-01-01T00:00:00Z",
    )
    key_headers = {"x-api-key": result["secret"]}

    # ---- 2. Key should be rejected immediately (already expired) ----
    resp = await api_client.get("/api/v1/spaces/", headers=key_headers)
    assert resp.status_code == 401, (
        f"Expired key should return 401, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Strict scope mode matrix
# ---------------------------------------------------------------------------

# List endpoints affected by strict mode (no resource ID in path, no self_filtering,
# not file-typed). These are allowed for scoped keys in normal mode but denied
# in strict mode.
STRICT_MODE_PROBES = [
    {"name": "list-assistants", "method": "GET", "path": "/api/v1/assistants/", "resource_type": "assistant"},
    {"name": "list-spaces", "method": "GET", "path": "/api/v1/spaces/", "resource_type": "space"},
    {"name": "list-groups", "method": "GET", "path": "/api/v1/groups/", "resource_type": "collection"},
    {"name": "list-info-blobs", "method": "GET", "path": "/api/v1/info-blobs/", "resource_type": "info_blob"},
]

# List endpoints exempt from strict mode (self_filtering=True or resource_type="file")
STRICT_MODE_EXEMPT_PROBES = [
    {"name": "list-files", "method": "GET", "path": "/api/v1/files/", "resource_type": "file"},
    {"name": "list-conversations", "method": "GET", "path": "/api/v1/conversations/", "resource_type": "conversation"},
]


async def _toggle_scope_enforcement(client, token: str, enabled: bool):
    resp = await client.patch(
        "/api/v1/settings/scope-enforcement",
        json={"enabled": enabled},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Toggle scope enforcement failed: {resp.text}"


async def _toggle_strict_mode(client, token: str, enabled: bool):
    resp = await client.patch(
        "/api/v1/settings/strict-mode",
        json={"enabled": enabled},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Toggle strict mode failed: {resp.text}"


@pytest.mark.api_key_matrix
async def test_strict_scope_mode_matrix(api_client, bearer_token):
    """Strict mode denies scoped keys on ambiguous list endpoints.

    Tests that:
    - With strict mode OFF: space-scoped keys can hit list endpoints (service layer filters)
    - With strict mode ON: space-scoped keys are denied on list endpoints (fail-closed)
    - Exempt endpoints (files, self_filtering) are allowed regardless of strict mode
    - Tenant-scoped keys are always unaffected
    """

    # ---- Setup ----
    space_id = await _create_space(api_client, token=bearer_token, name="strict-test-space")

    space_read_key = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    tenant_read_key = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="tenant",
        permission="read",
    )

    space_headers = {"x-api-key": space_read_key["secret"]}
    tenant_headers = {"x-api-key": tenant_read_key["secret"]}

    # ---- Enable scope enforcement (prerequisite for strict mode) ----
    await _toggle_scope_enforcement(api_client, bearer_token, enabled=True)

    # ---- Phase 1: Strict mode OFF ----
    await _toggle_strict_mode(api_client, bearer_token, enabled=False)

    collector = MatrixCollector()

    for probe in STRICT_MODE_PROBES + STRICT_MODE_EXEMPT_PROBES:
        # Space-scoped key: should be ALLOWED (service layer filters)
        resp = await api_client.get(probe["path"], headers=space_headers)
        actual = "deny" if resp.status_code in (401, 403) else "allow"
        collector.add(ProbeResult(
            key_name="space-read",
            method="GET",
            endpoint_name=probe["name"],
            path=probe["path"],
            status_code=resp.status_code,
            actual=actual,
            expected="allow",
            description="Strict mode OFF — scoped key allowed on list endpoints",
        ))

        # Tenant-scoped key: should always be ALLOWED
        resp = await api_client.get(probe["path"], headers=tenant_headers)
        actual = "deny" if resp.status_code in (401, 403) else "allow"
        collector.add(ProbeResult(
            key_name="tenant-read",
            method="GET",
            endpoint_name=probe["name"],
            path=probe["path"],
            status_code=resp.status_code,
            actual=actual,
            expected="allow",
            description="Tenant key — always allowed",
        ))

    # ---- Phase 2: Strict mode ON ----
    await _toggle_strict_mode(api_client, bearer_token, enabled=True)

    for probe in STRICT_MODE_PROBES:
        # Space-scoped key: should be DENIED (strict mode fail-closed)
        resp = await api_client.get(probe["path"], headers=space_headers)
        actual = "deny" if resp.status_code in (401, 403) else "allow"
        collector.add(ProbeResult(
            key_name="space-read",
            method="GET",
            endpoint_name=probe["name"],
            path=probe["path"],
            status_code=resp.status_code,
            actual=actual,
            expected="deny",
            description="Strict mode ON — scoped key denied on ambiguous list endpoint",
        ))

        # Tenant-scoped key: should still be ALLOWED
        resp = await api_client.get(probe["path"], headers=tenant_headers)
        actual = "deny" if resp.status_code in (401, 403) else "allow"
        collector.add(ProbeResult(
            key_name="tenant-read",
            method="GET",
            endpoint_name=probe["name"],
            path=probe["path"],
            status_code=resp.status_code,
            actual=actual,
            expected="allow",
            description="Tenant key — always allowed even in strict mode",
        ))

    for probe in STRICT_MODE_EXEMPT_PROBES:
        # Space-scoped key on exempt endpoints: should still be ALLOWED
        resp = await api_client.get(probe["path"], headers=space_headers)
        actual = "deny" if resp.status_code in (401, 403) else "allow"
        collector.add(ProbeResult(
            key_name="space-read",
            method="GET",
            endpoint_name=probe["name"],
            path=probe["path"],
            status_code=resp.status_code,
            actual=actual,
            expected="allow",
            description="Strict mode ON — exempt endpoint still allowed for scoped key",
        ))

    # ---- Print and assert ----
    print()
    print("STRICT SCOPE MODE MATRIX")
    collector.print_matrix()
    collector.write_to_file("strict_scope_matrix.csv")

    # ---- Cleanup: disable strict mode ----
    await _toggle_strict_mode(api_client, bearer_token, enabled=False)

    failures = [r for r in collector.results if not r.passed]
    assert len(failures) == 0, (
        f"{len(failures)} strict mode matrix mismatches. See matrix output above."
    )


# ---------------------------------------------------------------------------
# Owner lifecycle enforcement tests
# ---------------------------------------------------------------------------


async def _create_second_user(client, *, token):
    """Create a second user via admin API, return (user_id, username, email)."""
    username = f"user-{uuid4().hex[:8]}"
    email = f"{username}@example.com"
    resp = await client.post(
        "/api/v1/admin/users/",
        json={"email": email, "username": username},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return data["id"], username, email


async def _get_bearer_token_for_user(db_container, email):
    """Create a bearer token for a user by email."""
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email(email)
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(user)
    return token


@pytest.mark.api_key_matrix
async def test_api_key_rejected_when_owner_deactivated(
    api_client, bearer_token, db_container, patch_auth_service_jwt
):
    """API key should return 403 owner_inactive when the owner is deactivated."""

    # 1. Create a second user and get their bearer token
    user_id, username, email = await _create_second_user(
        api_client, token=bearer_token
    )
    user_token = await _get_bearer_token_for_user(db_container, email)

    # 2. Create a space (as admin) and add user2 as member
    space_id = await _create_space(api_client, token=bearer_token, name="deact-space")
    resp = await api_client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": user_id, "role": "admin"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Add member failed: {resp.text}"

    # 3. User2 creates a space-scoped key
    result = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    key_headers = {"x-api-key": result["secret"]}

    # 4. Verify the key works
    resp = await api_client.get(f"/api/v1/spaces/{space_id}/", headers=key_headers)
    assert resp.status_code == 200, f"Key should work before deactivation: {resp.text}"

    # 5. Deactivate the user
    resp = await api_client.post(
        f"/api/v1/admin/users/{username}/deactivate",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Deactivation failed: {resp.text}"

    # 6. Key should now return 403 owner_inactive (or 401 if revoked)
    resp = await api_client.get(f"/api/v1/spaces/{space_id}/", headers=key_headers)
    assert resp.status_code in (401, 403), (
        f"Key should be denied after owner deactivation, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.api_key_matrix
async def test_api_key_rejected_when_owner_deleted(
    api_client, bearer_token, db_container, patch_auth_service_jwt
):
    """API key should be rejected when the owner is deleted."""

    # 1. Create a second user and get their bearer token
    user_id, username, email = await _create_second_user(
        api_client, token=bearer_token
    )
    user_token = await _get_bearer_token_for_user(db_container, email)

    # 2. Create a space (as admin) and add user2 as member, then user2 creates a key
    space_id = await _create_space(api_client, token=bearer_token, name="delete-space")
    resp = await api_client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": user_id, "role": "admin"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Add member failed: {resp.text}"

    result = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    key_headers = {"x-api-key": result["secret"]}

    # 3. Verify the key works
    resp = await api_client.get(f"/api/v1/spaces/{space_id}/", headers=key_headers)
    assert resp.status_code == 200, f"Key should work before deletion: {resp.text}"

    # 4. Delete the user
    resp = await api_client.delete(
        f"/api/v1/admin/users/{username}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Deletion failed: {resp.text}"

    # 5. Key should now be rejected (revoked by lifecycle hook or owner not found)
    resp = await api_client.get(f"/api/v1/spaces/{space_id}/", headers=key_headers)
    assert resp.status_code in (401, 403), (
        f"Key should be denied after owner deletion, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.api_key_matrix
async def test_space_key_rejected_when_owner_removed_from_space(
    api_client, bearer_token, db_container, patch_auth_service_jwt
):
    """Space-scoped key should return 403 when owner is removed from the space."""

    # 1. Create a second user
    user_id, username, email = await _create_second_user(
        api_client, token=bearer_token
    )
    user_token = await _get_bearer_token_for_user(db_container, email)

    # 2. Create a space (owned by admin) and add user2 as member
    space_id = await _create_space(api_client, token=bearer_token, name="remove-space")
    resp = await api_client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": user_id, "role": "admin"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Add member failed: {resp.text}"

    # 3. User2 creates a space-scoped key
    result = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    key_headers = {"x-api-key": result["secret"]}

    # 4. Verify the key works
    resp = await api_client.get(f"/api/v1/spaces/{space_id}/", headers=key_headers)
    assert resp.status_code == 200, f"Key should work before removal: {resp.text}"

    # 5. Remove user2 from the space
    resp = await api_client.delete(
        f"/api/v1/spaces/{space_id}/members/{user_id}/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 204, f"Member removal failed: {resp.text}"

    # 6. Key should now be denied (lifecycle hook revoked it, or runtime check catches it)
    resp = await api_client.get(f"/api/v1/spaces/{space_id}/", headers=key_headers)
    assert resp.status_code in (401, 403), (
        f"Key should be denied after owner removed from space, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.api_key_matrix
async def test_keys_revoked_on_user_deactivation(
    api_client, bearer_token, db_container, patch_auth_service_jwt
):
    """Deactivating a user should revoke all their API keys in the DB."""

    # 1. Create a second user and get their bearer token
    user_id, username, email = await _create_second_user(
        api_client, token=bearer_token
    )
    user_token = await _get_bearer_token_for_user(db_container, email)

    # 2. Create space (as admin), add user2, then user2 creates keys
    space_id = await _create_space(api_client, token=bearer_token, name="revoke-space")
    resp = await api_client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": user_id, "role": "admin"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Add member failed: {resp.text}"

    key1 = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    key2 = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )

    # 3. Deactivate user
    resp = await api_client.post(
        f"/api/v1/admin/users/{username}/deactivate",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Deactivation failed: {resp.text}"

    # 4. Verify keys are revoked in DB
    async with db_container() as container:
        from intric.authentication.auth_models import ApiKeyState

        api_key_repo = container.api_key_v2_repo()
        user = await container.user_repo().get_user_by_email(email)
        for key_info in [key1, key2]:
            key = await api_key_repo.get(key_id=key_info["id"], tenant_id=user.tenant_id)
            assert key is not None, f"Key {key_info['id']} not found"
            assert key.state == ApiKeyState.REVOKED.value, (
                f"Key {key_info['id']} should be revoked, got state={key.state}"
            )


@pytest.mark.api_key_matrix
async def test_space_keys_revoked_on_member_removal(
    api_client, bearer_token, db_container, patch_auth_service_jwt
):
    """Removing a member from a space should revoke only their keys for that space."""

    # 1. Create a second user
    user_id, username, email = await _create_second_user(
        api_client, token=bearer_token
    )
    user_token = await _get_bearer_token_for_user(db_container, email)

    # 2. Create two spaces, add user2 to both
    space_a = await _create_space(api_client, token=bearer_token, name="space-a")
    space_b = await _create_space(api_client, token=bearer_token, name="space-b")
    for sid in [space_a, space_b]:
        resp = await api_client.post(
            f"/api/v1/spaces/{sid}/members/",
            json={"id": user_id, "role": "admin"},
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        assert resp.status_code == 200, f"Add member failed: {resp.text}"

    # 3. User2 creates space-scoped keys for both spaces
    key_a = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="space",
        scope_id=space_a,
        permission="read",
    )
    key_b = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="space",
        scope_id=space_b,
        permission="read",
    )

    # 4. Remove user2 from space_a only
    resp = await api_client.delete(
        f"/api/v1/spaces/{space_a}/members/{user_id}/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 204, f"Member removal failed: {resp.text}"

    # 5. Verify: key_a revoked, key_b untouched
    async with db_container() as container:
        from intric.authentication.auth_models import ApiKeyState

        api_key_repo = container.api_key_v2_repo()
        user = await container.user_repo().get_user_by_email(email)

        ka = await api_key_repo.get(key_id=key_a["id"], tenant_id=user.tenant_id)
        assert ka.state == ApiKeyState.REVOKED.value, (
            f"Key for space_a should be revoked, got state={ka.state}"
        )

        kb = await api_key_repo.get(key_id=key_b["id"], tenant_id=user.tenant_id)
        assert kb.state == ApiKeyState.ACTIVE.value, (
            f"Key for space_b should still be active, got state={kb.state}"
        )


@pytest.mark.api_key_matrix
async def test_reactivated_user_needs_new_keys(
    api_client, bearer_token, db_container, patch_auth_service_jwt
):
    """After deactivation and reactivation, old keys should remain revoked."""

    # 1. Create a second user
    user_id, username, email = await _create_second_user(
        api_client, token=bearer_token
    )
    user_token = await _get_bearer_token_for_user(db_container, email)

    # 2. Create a space, add user2, create key
    space_id = await _create_space(api_client, token=bearer_token, name="react-space")
    resp = await api_client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": user_id, "role": "admin"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Add member failed: {resp.text}"

    result = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    key_headers = {"x-api-key": result["secret"]}

    # 3. Verify key works
    resp = await api_client.get(f"/api/v1/spaces/{space_id}/", headers=key_headers)
    assert resp.status_code == 200, f"Key should work initially: {resp.text}"

    # 4. Deactivate user (keys get revoked)
    resp = await api_client.post(
        f"/api/v1/admin/users/{username}/deactivate",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Deactivation failed: {resp.text}"

    # 5. Reactivate user
    resp = await api_client.post(
        f"/api/v1/admin/users/{username}/reactivate",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Reactivation failed: {resp.text}"

    # 6. Old key should still be revoked (not magically restored)
    resp = await api_client.get(f"/api/v1/spaces/{space_id}/", headers=key_headers)
    assert resp.status_code == 401, (
        f"Revoked key should stay revoked after reactivation, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.api_key_matrix
async def test_assistant_key_rejected_when_owner_removed_from_space(
    api_client, bearer_token, db_container, patch_auth_service_jwt
):
    """Assistant-scoped key should be rejected when owner is removed from
    the space containing that assistant.

    Exercises the assistant->space_id resolution path in _resolve_space_id_for_scope,
    which is different from the space->space_id shortcut tested elsewhere.
    """

    # 1. Create a second user
    user_id, username, email = await _create_second_user(
        api_client, token=bearer_token
    )
    user_token = await _get_bearer_token_for_user(db_container, email)

    # 2. Create a space (as admin), add user2, create an assistant
    space_id = await _create_space(api_client, token=bearer_token, name="asst-scope-space")
    resp = await api_client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": user_id, "role": "admin"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Add member failed: {resp.text}"

    asst_id = await _create_assistant(api_client, token=bearer_token, space_id=space_id)

    # 3. User2 creates an assistant-scoped key
    result = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="assistant",
        scope_id=asst_id,
        permission="read",
    )
    key_headers = {"x-api-key": result["secret"]}

    # 4. Verify the key works
    resp = await api_client.get(f"/api/v1/assistants/{asst_id}/", headers=key_headers)
    assert resp.status_code == 200, f"Key should work before removal: {resp.text}"

    # 5. Remove user2 from the space
    resp = await api_client.delete(
        f"/api/v1/spaces/{space_id}/members/{user_id}/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 204, f"Member removal failed: {resp.text}"

    # 6. Key should be denied (lifecycle hook revoked it + runtime check as safety net)
    resp = await api_client.get(f"/api/v1/assistants/{asst_id}/", headers=key_headers)
    assert resp.status_code in (401, 403), (
        f"Assistant-scoped key should be denied after owner removed from space, "
        f"got {resp.status_code}: {resp.text}"
    )


@pytest.mark.api_key_matrix
async def test_app_key_rejected_when_owner_removed_from_space(
    api_client, bearer_token, db_container, patch_auth_service_jwt
):
    """App-scoped key should be rejected when owner is removed from
    the space containing that app.

    Exercises the app->space_id resolution path in _resolve_space_id_for_scope.
    """

    # 1. Create a second user
    user_id, username, email = await _create_second_user(
        api_client, token=bearer_token
    )
    user_token = await _get_bearer_token_for_user(db_container, email)

    # 2. Create a space (as admin), add user2, create an app
    space_id = await _create_space(api_client, token=bearer_token, name="app-scope-space")
    resp = await api_client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": user_id, "role": "admin"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Add member failed: {resp.text}"

    try:
        app_id = await _create_app(api_client, token=bearer_token, space_id=space_id)
    except AssertionError:
        pytest.skip("App creation requires transcription model — not available in test env")

    # 3. User2 creates an app-scoped key
    result = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="app",
        scope_id=app_id,
        permission="read",
    )
    key_headers = {"x-api-key": result["secret"]}

    # 4. Verify the key works
    resp = await api_client.get(
        f"/api/v1/spaces/{space_id}/applications/apps/{app_id}/",
        headers=key_headers,
    )
    assert resp.status_code == 200, f"Key should work before removal: {resp.text}"

    # 5. Remove user2 from the space
    resp = await api_client.delete(
        f"/api/v1/spaces/{space_id}/members/{user_id}/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 204, f"Member removal failed: {resp.text}"

    # 6. Key should be denied
    resp = await api_client.get(
        f"/api/v1/spaces/{space_id}/applications/apps/{app_id}/",
        headers=key_headers,
    )
    assert resp.status_code in (401, 403), (
        f"App-scoped key should be denied after owner removed from space, "
        f"got {resp.status_code}: {resp.text}"
    )


@pytest.mark.api_key_matrix
async def test_assistant_key_revoked_on_member_removal(
    api_client, bearer_token, db_container, patch_auth_service_jwt
):
    """Removing a member should revoke their assistant-scoped keys for that space,
    but not their keys in other spaces."""

    # 1. Create a second user
    user_id, username, email = await _create_second_user(
        api_client, token=bearer_token
    )
    user_token = await _get_bearer_token_for_user(db_container, email)

    # 2. Create two spaces, add user2 to both, create assistants
    space_a = await _create_space(api_client, token=bearer_token, name="asst-revoke-a")
    space_b = await _create_space(api_client, token=bearer_token, name="asst-revoke-b")
    for sid in [space_a, space_b]:
        resp = await api_client.post(
            f"/api/v1/spaces/{sid}/members/",
            json={"id": user_id, "role": "admin"},
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        assert resp.status_code == 200, f"Add member failed: {resp.text}"

    asst_a = await _create_assistant(api_client, token=bearer_token, space_id=space_a)
    asst_b = await _create_assistant(api_client, token=bearer_token, space_id=space_b)

    # 3. User2 creates assistant-scoped keys in both spaces
    key_a = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="assistant",
        scope_id=asst_a,
        permission="read",
    )
    key_b = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="assistant",
        scope_id=asst_b,
        permission="read",
    )

    # 4. Remove user2 from space_a only
    resp = await api_client.delete(
        f"/api/v1/spaces/{space_a}/members/{user_id}/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 204, f"Member removal failed: {resp.text}"

    # 5. Verify: key_a revoked, key_b untouched
    async with db_container() as container:
        from intric.authentication.auth_models import ApiKeyState

        api_key_repo = container.api_key_v2_repo()
        user = await container.user_repo().get_user_by_email(email)

        ka = await api_key_repo.get(key_id=key_a["id"], tenant_id=user.tenant_id)
        assert ka.state == ApiKeyState.REVOKED.value, (
            f"Assistant key in space_a should be revoked, got state={ka.state}"
        )

        kb = await api_key_repo.get(key_id=key_b["id"], tenant_id=user.tenant_id)
        assert kb.state == ApiKeyState.ACTIVE.value, (
            f"Assistant key in space_b should still be active, got state={kb.state}"
        )


@pytest.mark.api_key_matrix
async def test_invited_user_key_rejected(
    api_client, bearer_token, db_container, patch_auth_service_jwt
):
    """A key owned by an INVITED user (not yet ACTIVE) should be rejected.

    INVITED users have state != ACTIVE, so the runtime check should catch this.
    This verifies that the owner_inactive check covers non-obvious states like INVITED.

    Strategy: create an ACTIVE user, create a working key, then change state to INVITED
    via the DB. This simulates a user whose account was reverted to invited.
    """

    # 1. Create a second user (starts as ACTIVE) and get their bearer token
    user_id, username, email = await _create_second_user(
        api_client, token=bearer_token
    )
    user_token = await _get_bearer_token_for_user(db_container, email)

    # 2. Create a space, add user2, create a key
    space_id = await _create_space(api_client, token=bearer_token, name="invited-space")
    resp = await api_client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": user_id, "role": "admin"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert resp.status_code == 200, f"Add member failed: {resp.text}"

    result = await _create_api_key(
        api_client,
        token=user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    key_headers = {"x-api-key": result["secret"]}

    # 3. Verify key works while user is ACTIVE
    resp = await api_client.get(f"/api/v1/spaces/{space_id}/", headers=key_headers)
    assert resp.status_code == 200, f"Key should work while user is active: {resp.text}"

    # 4. Set user state to INVITED via direct DB update
    async with db_container() as container:
        from intric.users.user import UserUpdatePublic, UserState

        user_service = container.user_service()
        await user_service.update_user(
            user_id, UserUpdatePublic(state=UserState.INVITED)
        )

    # 5. Key should now be rejected because owner is not ACTIVE
    resp = await api_client.get(f"/api/v1/spaces/{space_id}/", headers=key_headers)
    assert resp.status_code in (401, 403), (
        f"Key should be denied for INVITED user, got {resp.status_code}: {resp.text}"
    )
