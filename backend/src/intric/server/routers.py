from fastapi import APIRouter

from intric.admin.admin_router import router as admin_router
from intric.ai_models.ai_models_router import router as ai_models_router
from intric.allowed_origins.allowed_origin_router import (
    router as allowed_origins_router,
)
from intric.analysis.analysis_router import router as analysis_router
from intric.apps.app_runs.api.app_run_router import router as app_run_router
from intric.apps.apps.api.app_router import router as app_router
from intric.assistants.api.assistant_router import router as assistants_router
from intric.completion_models.presentation.completion_models_router import (
    router as completion_models_router,
)
from intric.conversations.conversations_router import router as conversations_router
from intric.crawler.crawl_run_router import router as crawl_run_router
from intric.dashboard.api.dashboard_router import router as dashboard_router
from intric.embedding_models.presentation.embedding_model_router import (
    router as embedding_models_router,
)
from intric.files.file_router import router as files_router
from intric.group_chat.presentation.group_chat_router import router as group_chat_router
from intric.groups_legacy.api.group_router import router as groups_router
from intric.icons.api.icon_router import router as icons_router
from intric.info_blobs.info_blobs_router import router as info_blobs_router
from intric.integration.presentation.integration_auth_router import (
    router as integration_auth_router,
)
from intric.integration.presentation.integration_router import (
    router as integration_router,
)
from intric.integration.presentation.sharepoint_webhook_router import (
    router as sharepoint_webhook_router,
)
from intric.integration.presentation.admin_sharepoint_router import (
    router as admin_sharepoint_router,
)
from intric.jobs.job_router import router as jobs_router
from intric.limits.limit_router import router as limit_router
from intric.logging.logging_router import router as logging_router
from intric.main.config import get_settings
from intric.prompts.api.prompt_router import router as prompt_router
from intric.security_classifications.presentation.security_classification_router import (
    router as security_classifications_router,
)
from intric.server.websockets.websocket_router import router as websocket_router
from intric.services.service_router import router as services_router
from intric.settings.settings_router import router as settings_router
from intric.spaces.api.space_router import router as space_router
from intric.storage.presentation.storage_router import router as storage_router
from intric.templates.api.templates_router import router as template_router
from intric.templates.app_template.api.app_template_router import (
    router as app_template_router,
)
from intric.templates.assistant_template.api.assistant_template_router import (
    router as assistant_template_router,
)
from intric.templates.assistant_template.api.admin_router import (
    router as assistant_template_admin_router,
)
from intric.templates.app_template.api.admin_router import (
    router as app_template_admin_router,
)
from intric.token_usage.presentation.token_usage_router import (
    router as token_usage_router,
)
from intric.transcription_models.presentation.transcription_models_router import (
    router as transcription_models_router,
)
from intric.image_models.presentation.image_models_router import (
    router as image_models_router,
)
from intric.user_groups.user_groups_router import router as user_groups_router
from intric.users.user_router import router as users_router
from intric.websites.presentation.website_router import router as website_router
from intric.modules.module_router import router as module_router
from intric.sysadmin.sysadmin_router import router as sysadmin_router
from intric.tenants.presentation.tenant_credentials_router import (
    router as tenant_credentials_router,
)
from intric.tenants.presentation.tenant_crawler_settings_router import (
    router as tenant_crawler_settings_router,
)
from intric.tenants.presentation.tenant_self_credentials_router import (
    router as tenant_self_credentials_router,
)
from intric.tenants.presentation.tenant_federation_router import (
    router as tenant_federation_router,
)
from intric.authentication.federation_router import router as federation_router
from intric.api.documentation.openapi_endpoints import router as documentation_router

router = APIRouter()

router.include_router(crawl_run_router, prefix="/crawl-runs", tags=["crawl-runs"])
router.include_router(app_router, prefix="/apps", tags=["apps"])
router.include_router(app_run_router, prefix="/app-runs", tags=["app-runs"])
router.include_router(users_router, prefix="/users", tags=["users"])
router.include_router(info_blobs_router, prefix="/info-blobs", tags=["info-blobs"])
router.include_router(groups_router, prefix="/groups", tags=["groups"])
router.include_router(settings_router, prefix="/settings", tags=["settings"])
router.include_router(assistants_router, prefix="/assistants", tags=["assistants"])
router.include_router(group_chat_router, prefix="/group-chats", tags=["group-chats"])
router.include_router(conversations_router, prefix="/conversations", tags=["conversations"])
router.include_router(services_router, prefix="/services", tags=["services"])
router.include_router(logging_router, prefix="/logging", tags=["logging"])
router.include_router(analysis_router, prefix="/analysis", tags=["analysis"])
router.include_router(admin_router, prefix="/admin", tags=["admin"])
router.include_router(tenant_self_credentials_router, prefix="/admin", tags=["admin"])
router.include_router(assistant_template_admin_router, prefix="", tags=["admin-templates"])
router.include_router(app_template_admin_router, prefix="", tags=["admin-templates"])
router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
router.include_router(user_groups_router, prefix="/user-groups", tags=["user-groups"])
router.include_router(allowed_origins_router, prefix="/allowed-origins", tags=["allowed-origins"])
router.include_router(
    completion_models_router, prefix="/completion-models", tags=["completion-models"]
)
router.include_router(
    embedding_models_router, prefix="/embedding-models", tags=["embedding-models"]
)
router.include_router(
    transcription_models_router,
    prefix="/transcription-models",
    tags=["transcription-models"],
)
router.include_router(
    image_models_router,
    prefix="/image-models",
    tags=["image-models"],
)
router.include_router(files_router, prefix="/files", tags=["files"])
router.include_router(icons_router, prefix="/icons", tags=["icons"])
router.include_router(limit_router, prefix="/limits", tags=["limits"])
router.include_router(space_router, prefix="/spaces", tags=["spaces"])
router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
router.include_router(website_router, prefix="/websites", tags=["websites"])
router.include_router(websocket_router, prefix="", tags=["websockets"])
router.include_router(prompt_router, prefix="/prompts", tags=["prompts"])
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
router.include_router(storage_router, prefix="/storage", tags=["storage"])
router.include_router(token_usage_router, prefix="/token-usage", tags=["token-usage"])
router.include_router(
    security_classifications_router,
    prefix="/security-classifications",
    tags=["security-classifications"],
)
router.include_router(integration_router, prefix="/integrations", tags=["integrations"])
router.include_router(sharepoint_webhook_router, prefix="/integrations", tags=["integrations"])
router.include_router(admin_sharepoint_router, prefix="/admin", tags=["admin"])
router.include_router(ai_models_router, prefix="/ai-models", tags=["ai-models"])

router.include_router(integration_auth_router, prefix="/integrations/auth", tags=["integrations"])

router.include_router(sysadmin_router, prefix="/sysadmin", tags=["sysadmin"])
router.include_router(tenant_credentials_router, prefix="/sysadmin", tags=["sysadmin"])
router.include_router(tenant_crawler_settings_router, prefix="/sysadmin", tags=["sysadmin"])
router.include_router(tenant_federation_router, prefix="/sysadmin", tags=["sysadmin"])
router.include_router(module_router, prefix="/modules", tags=["modules"])
router.include_router(federation_router, prefix="", tags=["authentication"])  # Public auth endpoints (no prefix)
router.include_router(documentation_router, prefix="")

if get_settings().using_access_management:
    from intric.roles.roles_router import router as roles_router

    router.include_router(roles_router, prefix="/roles", tags=["roles"])
