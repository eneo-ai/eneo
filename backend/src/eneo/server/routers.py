from fastapi import APIRouter, Depends

from eneo.admin.admin_router import router as admin_router
from eneo.ai_models.ai_models_router import router as ai_models_router
from eneo.allowed_origins.allowed_origin_router import (
    router as allowed_origins_router,
)
from eneo.analysis.analysis_router import router as analysis_router
from eneo.api.audit.routes import router as audit_router
from eneo.api.documentation.openapi_endpoints import router as documentation_router
from eneo.apps.app_runs.api.app_run_router import router as app_run_router
from eneo.apps.apps.api.app_router import router as app_router
from eneo.assistants.api.assistant_router import router as assistants_router
from eneo.authentication.api_key_router import router as api_key_router
from eneo.authentication.auth_dependencies import (
    APPS_READ_OVERRIDES,
    ASSISTANTS_READ_OVERRIDES,
    CONVERSATIONS_READ_OVERRIDES,
    FILES_READ_OVERRIDES,
    KNOWLEDGE_READ_OVERRIDES,
    require_api_key_permission,
    require_api_key_scope_check,
    require_file_delete_scope_guard,
    require_resource_permission_for_method,
)
from eneo.authentication.auth_models import ApiKeyPermission
from eneo.authentication.federation_router import router as federation_router
from eneo.completion_models.presentation.completion_models_router import (
    router as completion_models_router,
)
from eneo.completion_models.presentation.tenant_completion_models_router import (
    router as tenant_completion_models_router,
)
from eneo.conversations.conversations_router import router as conversations_router
from eneo.crawler.crawl_run_router import router as crawl_run_router
from eneo.dashboard.api.dashboard_router import router as dashboard_router
from eneo.embedding_models.presentation.embedding_model_router import (
    router as embedding_models_router,
)
from eneo.embedding_models.presentation.tenant_embedding_models_router import (
    router as tenant_embedding_models_router,
)
from eneo.files.file_router import router as files_router
from eneo.governance_policy.presentation.governance_policy_router import (
    router as governance_policy_router,
)
from eneo.group_chat.presentation.group_chat_router import router as group_chat_router
from eneo.groups_legacy.api.group_router import router as groups_router
from eneo.help_assistants.api.admin_router import (
    router as help_assistants_admin_router,
)
from eneo.help_assistants.api.run_router import (
    router as help_assistants_run_router,
)
from eneo.icons.api.icon_router import router as icons_router
from eneo.info_blobs.info_blobs_router import router as info_blobs_router
from eneo.integration.presentation.admin_sharepoint_router import (
    router as admin_sharepoint_router,
)
from eneo.integration.presentation.integration_auth_router import (
    router as integration_auth_router,
)
from eneo.integration.presentation.integration_router import (
    router as integration_router,
)
from eneo.integration.presentation.sharepoint_webhook_router import (
    router as sharepoint_webhook_router,
)
from eneo.jobs.job_router import router as jobs_router
from eneo.limits.limit_router import router as limit_router
from eneo.logging.logging_router import router as logging_router
from eneo.main.config import get_settings
from eneo.mcp_servers.presentation.mcp_server_router import (
    router as mcp_server_router,
)
from eneo.model_providers.presentation.model_provider_router import (
    router as model_providers_router,
)
from eneo.modules.module_router import router as module_router
from eneo.prompt_library.presentation.prompt_library_router import (
    router as prompt_library_router,
)
from eneo.prompts.api.prompt_router import router as prompt_router
from eneo.security_classifications.presentation.security_classification_router import (
    router as security_classifications_router,
)
from eneo.server.websockets.websocket_router import router as websocket_router
from eneo.services.service_router import router as services_router
from eneo.settings.settings_router import (
    router as settings_router,
)
from eneo.settings.settings_router import (
    settings_admin_router,
)
from eneo.spaces.api.space_router import router as space_router
from eneo.storage.presentation.storage_router import router as storage_router
from eneo.sysadmin.sysadmin_router import router as sysadmin_router
from eneo.templates.api.templates_router import router as template_router
from eneo.templates.app_template.api.admin_router import (
    router as app_template_admin_router,
)
from eneo.templates.app_template.api.app_template_router import (
    router as app_template_router,
)
from eneo.templates.assistant_template.api.admin_router import (
    router as assistant_template_admin_router,
)
from eneo.templates.assistant_template.api.assistant_template_router import (
    router as assistant_template_router,
)
from eneo.tenants.presentation.tenant_crawler_settings_router import (
    router as tenant_crawler_settings_router,
)
from eneo.tenants.presentation.tenant_credentials_router import (
    router as tenant_credentials_router,
)
from eneo.tenants.presentation.tenant_federation_router import (
    router as tenant_federation_router,
)
from eneo.tenants.presentation.tenant_self_credentials_router import (
    router as tenant_self_credentials_router,
)
from eneo.token_usage.presentation.token_usage_router import (
    router as token_usage_router,
)
from eneo.transcription_models.presentation.tenant_transcription_models_router import (
    router as tenant_transcription_models_router,
)
from eneo.transcription_models.presentation.transcription_models_router import (
    router as transcription_models_router,
)
from eneo.user_groups.user_groups_router import router as user_groups_router
from eneo.users.user_router import router as users_router
from eneo.users.user_router import users_admin_router
from eneo.websites.presentation.website_router import router as website_router

router = APIRouter()

TENANT_ADMIN_SCOPE_GUARDS = (
    Depends(require_api_key_scope_check(resource_type="admin", path_param=None)),
)
TENANT_ADMIN_API_KEY_GUARDS = (
    *TENANT_ADMIN_SCOPE_GUARDS,
    Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
)
router.include_router(
    crawl_run_router,
    prefix="/crawl-runs",
    tags=["crawl-runs"],
    dependencies=[
        Depends(require_resource_permission_for_method("knowledge")),
        Depends(
            require_api_key_scope_check(resource_type="crawl_run", path_param="id")
        ),
    ],
)
router.include_router(
    app_router,
    prefix="/apps",
    tags=["apps"],
    dependencies=[
        Depends(
            require_resource_permission_for_method(
                "apps", read_override_endpoints=APPS_READ_OVERRIDES
            )
        ),
        Depends(require_api_key_scope_check(resource_type="app", path_param="id")),
    ],
)
router.include_router(
    app_run_router,
    prefix="/app-runs",
    tags=["app-runs"],
    dependencies=[
        Depends(
            require_resource_permission_for_method(
                "apps", read_override_endpoints=APPS_READ_OVERRIDES
            )
        ),
        Depends(require_api_key_scope_check(resource_type="app_run", path_param="id")),
    ],
)
router.include_router(
    api_key_router,
    dependencies=[
        Depends(require_api_key_scope_check(resource_type="admin", path_param=None)),
    ],
)
router.include_router(
    users_admin_router,
    prefix="/users",
    tags=["users"],
    dependencies=[
        Depends(require_api_key_scope_check(resource_type="admin", path_param=None)),
        Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
    ],
)
router.include_router(users_router, prefix="/users", tags=["users"])
router.include_router(
    info_blobs_router,
    prefix="/info-blobs",
    tags=["info-blobs"],
    dependencies=[
        Depends(require_resource_permission_for_method("knowledge")),
        Depends(
            require_api_key_scope_check(resource_type="info_blob", path_param=None)
        ),
    ],
)
router.include_router(
    groups_router,
    prefix="/groups",
    tags=["groups"],
    dependencies=[
        Depends(
            require_resource_permission_for_method(
                "knowledge", read_override_endpoints=KNOWLEDGE_READ_OVERRIDES
            )
        ),
        Depends(
            require_api_key_scope_check(resource_type="collection", path_param="id")
        ),
    ],
)
router.include_router(settings_router, prefix="/settings", tags=["settings"])
router.include_router(
    settings_admin_router,
    prefix="/settings",
    tags=["settings"],
    dependencies=[
        Depends(require_api_key_scope_check(resource_type="admin", path_param=None)),
        Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
    ],
)
router.include_router(
    assistants_router,
    prefix="/assistants",
    tags=["assistants"],
    dependencies=[
        Depends(
            require_resource_permission_for_method(
                "assistants", read_override_endpoints=ASSISTANTS_READ_OVERRIDES
            )
        ),
        Depends(
            require_api_key_scope_check(resource_type="assistant", path_param="id")
        ),
    ],
)
router.include_router(
    group_chat_router,
    prefix="/group-chats",
    tags=["group-chats"],
    dependencies=[
        Depends(require_resource_permission_for_method("assistants")),
        Depends(
            require_api_key_scope_check(resource_type="group_chat", path_param="id")
        ),
    ],
)
router.include_router(
    conversations_router,
    prefix="/conversations",
    tags=["conversations"],
    dependencies=[
        Depends(
            require_resource_permission_for_method(
                "assistants", read_override_endpoints=CONVERSATIONS_READ_OVERRIDES
            )
        ),
        Depends(
            require_api_key_scope_check(
                resource_type="conversation",
                path_param="session_id",
                self_filtering=True,
            )
        ),
    ],
)
router.include_router(
    services_router,
    prefix="/services",
    tags=["services"],
    dependencies=[
        Depends(
            require_resource_permission_for_method(
                "apps", read_override_endpoints=APPS_READ_OVERRIDES
            )
        ),
        Depends(require_api_key_scope_check(resource_type="service", path_param="id")),
    ],
)
router.include_router(
    logging_router,
    prefix="/logging",
    tags=["logging"],
    dependencies=TENANT_ADMIN_SCOPE_GUARDS,
)
router.include_router(
    analysis_router,
    prefix="/analysis",
    tags=["analysis"],
    dependencies=TENANT_ADMIN_SCOPE_GUARDS,
)
router.include_router(
    admin_router,
    prefix="/admin",
    tags=["admin"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    tenant_self_credentials_router,
    prefix="/admin",
    tags=["admin"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    assistant_template_admin_router,
    prefix="",
    tags=["admin-templates"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    app_template_admin_router,
    prefix="",
    tags=["admin-templates"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    jobs_router,
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[
        *TENANT_ADMIN_SCOPE_GUARDS,
        Depends(require_resource_permission_for_method("jobs")),
    ],
)
router.include_router(
    user_groups_router,
    prefix="/user-groups",
    tags=["user-groups"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    allowed_origins_router,
    prefix="/allowed-origins",
    tags=["allowed-origins"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    completion_models_router,
    prefix="/completion-models",
    tags=["completion-models"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    embedding_models_router,
    prefix="/embedding-models",
    tags=["embedding-models"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    transcription_models_router,
    prefix="/transcription-models",
    tags=["transcription-models"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    model_providers_router,
    prefix="/admin/model-providers",
    tags=["admin", "model-providers"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    tenant_completion_models_router,
    prefix="/admin/tenant-models/completion",
    tags=["admin", "tenant-models"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    tenant_embedding_models_router,
    prefix="/admin/tenant-models/embedding",
    tags=["admin", "tenant-models"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    tenant_transcription_models_router,
    prefix="/admin/tenant-models/transcription",
    tags=["admin", "tenant-models"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    files_router,
    prefix="/files",
    tags=["files"],
    dependencies=[
        Depends(
            require_resource_permission_for_method(
                "files", read_override_endpoints=FILES_READ_OVERRIDES
            )
        ),
        Depends(require_api_key_scope_check(resource_type="file", path_param=None)),
        Depends(require_file_delete_scope_guard()),
    ],
)
router.include_router(icons_router, prefix="/icons", tags=["icons"])
router.include_router(limit_router, prefix="/limits", tags=["limits"])
router.include_router(
    space_router,
    prefix="/spaces",
    tags=["spaces"],
    dependencies=[
        Depends(require_resource_permission_for_method("spaces")),
        Depends(require_api_key_scope_check(resource_type="space", path_param="id")),
    ],
)
router.include_router(
    dashboard_router,
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[
        Depends(require_api_key_scope_check(resource_type="space", path_param=None)),
    ],
)
router.include_router(
    website_router,
    prefix="/websites",
    tags=["websites"],
    dependencies=[
        Depends(require_resource_permission_for_method("knowledge")),
        Depends(require_api_key_scope_check(resource_type="website", path_param="id")),
    ],
)
router.include_router(websocket_router, prefix="", tags=["websockets"])
router.include_router(
    prompt_router,
    prefix="/prompts",
    tags=["prompts"],
    dependencies=[
        Depends(require_resource_permission_for_method("prompts")),
        Depends(require_api_key_scope_check(resource_type="prompt", path_param="id")),
    ],
)
router.include_router(
    app_template_router,
    prefix="/templates/apps",
    tags=["apps-templates"],
)
router.include_router(
    assistant_template_router,
    prefix="/templates/assistants",
    tags=["assistants-templates"],
)
router.include_router(template_router, prefix="/templates", tags=["templates"])
router.include_router(
    storage_router,
    prefix="/storage",
    tags=["storage"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    token_usage_router,
    prefix="/token-usage",
    tags=["token-usage"],
    dependencies=[
        Depends(require_api_key_scope_check(resource_type="admin", path_param=None)),
        Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
    ],
)
router.include_router(
    security_classifications_router,
    prefix="/security-classifications",
    tags=["security-classifications"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    audit_router,
    prefix="",
    tags=["audit"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    integration_router,
    prefix="/integrations",
    tags=["integrations"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    mcp_server_router,
    prefix="/mcp-servers",
    tags=["mcp-servers"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    prompt_library_router,
    prefix="/admin/prompt-library",
    tags=["admin", "prompt-library"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    governance_policy_router,
    prefix="/admin/governance-policy",
    tags=["admin", "governance-policy"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    sharepoint_webhook_router, prefix="/integrations", tags=["integrations"]
)
router.include_router(
    admin_sharepoint_router,
    prefix="/admin",
    tags=["admin"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    help_assistants_admin_router,
    prefix="/admin/help-assistants",
    tags=["admin", "help-assistants"],
    dependencies=TENANT_ADMIN_API_KEY_GUARDS,
)
router.include_router(
    help_assistants_run_router,
    prefix="/help-assistants",
    tags=["help-assistants"],
)
router.include_router(ai_models_router, prefix="/ai-models", tags=["ai-models"])

router.include_router(
    integration_auth_router, prefix="/integrations/auth", tags=["integrations"]
)

router.include_router(sysadmin_router, prefix="/sysadmin", tags=["sysadmin"])
router.include_router(tenant_credentials_router, prefix="/sysadmin", tags=["sysadmin"])
router.include_router(
    tenant_crawler_settings_router, prefix="/sysadmin", tags=["sysadmin"]
)
router.include_router(tenant_federation_router, prefix="/sysadmin", tags=["sysadmin"])
router.include_router(module_router, prefix="/modules", tags=["modules"])
router.include_router(
    federation_router, prefix="", tags=["authentication"]
)  # Public auth endpoints (no prefix)
router.include_router(documentation_router, prefix="")

if get_settings().using_access_management:
    from eneo.roles.roles_router import router as roles_router

    router.include_router(
        roles_router,
        prefix="/roles",
        tags=["roles"],
        dependencies=TENANT_ADMIN_API_KEY_GUARDS,
    )
