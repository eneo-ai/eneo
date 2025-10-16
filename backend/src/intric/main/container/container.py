from dependency_injector import containers, providers
from intric.actors import ActorFactory, ActorManager
from intric.admin.admin_service import AdminService
from intric.admin.quota_service import QuotaService
from intric.ai_models.ai_models_service import AIModelsService
from intric.ai_models.completion_models.completion_models_repo import (
    CompletionModelsRepository,
)
from intric.ai_models.embedding_models.embedding_models_repo import (
    AdminEmbeddingModelsService,
)
from intric.allowed_origins.allowed_origin_repo import AllowedOriginRepository
from intric.allowed_origins.allowed_origin_service import AllowedOriginService
from intric.analysis.analysis_repo import AnalysisRepository
from intric.analysis.analysis_service import AnalysisService
from intric.apps import (
    AppAssembler,
    AppFactory,
    AppRepository,
    AppRunAssembler,
    AppRunFactory,
    AppRunRepository,
    AppRunService,
    AppService,
)
from intric.assistants.api.assistant_assembler import AssistantAssembler
from intric.assistants.assistant_factory import AssistantFactory
from intric.assistants.assistant_repo import AssistantRepository
from intric.assistants.assistant_service import AssistantService
from intric.assistants.references import ReferencesService
from intric.authentication.api_key_repo import ApiKeysRepository
from intric.authentication.auth_service import AuthService
from intric.collections.application.collection_crud_service import CollectionCRUDService
from intric.completion_models.application import CompletionModelCRUDService
from intric.completion_models.application.completion_model_migration_service import (
    CompletionModelMigrationService,
)
from intric.completion_models.application.completion_model_migration_history_service import (
    CompletionModelMigrationHistoryService,
)
from intric.completion_models.application.completion_model_usage_service import (
    CompletionModelUsageService,
)
from intric.completion_models.domain import CompletionModelRepository
from intric.completion_models.domain.completion_model_service import (
    CompletionModelService,
)
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.completion_models.infrastructure.context_builder import ContextBuilder
from intric.completion_models.presentation import CompletionModelAssembler
from intric.conversations.application.conversation_service import ConversationService
from intric.crawler.crawler import Crawler
from intric.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from intric.database.database import AsyncSession
from intric.embedding_models.application.embedding_model_crud_service import (
    EmbeddingModelCRUDService,
)
from intric.embedding_models.domain.embedding_model_repo import EmbeddingModelRepository
from intric.embedding_models.infrastructure.create_embeddings_service import (
    CreateEmbeddingsService,
)
from intric.embedding_models.infrastructure.datastore import Datastore
from intric.files.file_protocol import FileProtocol
from intric.files.file_repo import FileRepository
from intric.files.file_service import FileService
from intric.files.file_size_service import FileSizeService
from intric.files.image import ImageExtractor
from intric.files.text import TextExtractor
from intric.files.transcriber import Transcriber
from intric.group_chat.application.group_chat_service import GroupChatService
from intric.group_chat.presentation.assemblers.group_chat_assembler import (
    GroupChatAssembler,
)
from intric.groups_legacy.group_repo import GroupRepository
from intric.groups_legacy.group_service import GroupService
from intric.info_blobs.info_blob_chunk_repo import InfoBlobChunkRepo
from intric.info_blobs.info_blob_repo import InfoBlobRepository
from intric.info_blobs.info_blob_service import InfoBlobService
from intric.info_blobs.text_processor import TextProcessor
from intric.integration.application.integration_knowledge_service import (
    IntegrationKnowledgeService,
)
from intric.integration.application.integration_preview_service import (
    IntegrationPreviewService,
)
from intric.integration.application.integration_service import IntegrationService
from intric.integration.application.oauth2_service import Oauth2Service
from intric.integration.application.tenant_integration_service import (
    TenantIntegrationService,
)
from intric.integration.application.user_integration_service import (
    UserIntegrationService,
)
from intric.integration.infrastructure.auth_service.confluence_auth_service import (
    ConfluenceAuthService,
)
from intric.integration.infrastructure.auth_service.sharepoint_auth_service import (
    SharepointAuthService,
)
from intric.integration.infrastructure.content_service.confluence_content_service import (
    ConfluenceContentService,
)
from intric.integration.infrastructure.content_service.sharepoint_content_service import (
    SharePointContentService,
)
from intric.integration.infrastructure.mappers.integration_knowledge_mapper import (
    IntegrationKnowledgeMapper,
)
from intric.integration.infrastructure.mappers.integration_mapper import (
    IntegrationMapper,
)
from intric.integration.infrastructure.mappers.oauth_token_mapper import (
    OauthTokenMapper,
)
from intric.integration.infrastructure.mappers.tenant_integration_mapper import (
    TenantIntegrationMapper,
)
from intric.integration.infrastructure.mappers.user_integration_mapper import (
    UserIntegrationMapper,
)
from intric.integration.infrastructure.oauth_token_service import OauthTokenService
from intric.integration.infrastructure.preview_service.confluence_preview_service import (
    ConfluencePreviewService,
)
from intric.integration.infrastructure.preview_service.sharepoint_preview_service import (
    SharePointPreviewService,
)
from intric.integration.infrastructure.repo_impl.integration_knowledge_repo_impl import (
    IntegrationKnowledgeRepoImpl,
)
from intric.integration.infrastructure.repo_impl.integration_repo_impl import (
    IntegrationRepoImpl,
)
from intric.integration.infrastructure.repo_impl.oauth_token_repo_impl import (
    OauthTokenRepoImpl,
)
from intric.integration.infrastructure.repo_impl.tenant_integration_repo_impl import (
    TenantIntegrationRepoImpl,
)
from intric.integration.infrastructure.repo_impl.user_integration_repo_impl import (
    UserIntegrationRepoImpl,
)
from intric.integration.presentation.assemblers.confluence_content_assembler import (
    ConfluenceContentAssembler,
)
from intric.integration.presentation.assemblers.integration_assembler import (
    IntegrationAssembler,
)
from intric.integration.presentation.assemblers.integration_knowledge_assembler import (
    IntegrationKnowledgeAssembler,
)
from intric.integration.presentation.assemblers.tenant_integration_assembler import (
    TenantIntegrationAssembler,
)
from intric.integration.presentation.assemblers.user_integration_assembler import (
    UserIntegrationAssembler,
)
from intric.jobs.job_repo import JobRepository
from intric.jobs.job_service import JobService
from intric.jobs.task_service import TaskService
from intric.limits.limit_service import LimitService
from intric.main.aiohttp_client import aiohttp_client
from intric.modules.module_repo import ModuleRepository
from intric.predefined_roles.predefined_role_service import PredefinedRolesService
from intric.predefined_roles.predefined_roles_repo import PredefinedRolesRepository
from intric.prompts.api.prompt_assembler import PromptAssembler
from intric.prompts.prompt_factory import PromptFactory
from intric.prompts.prompt_repo import PromptRepository
from intric.prompts.prompt_service import PromptService
from intric.questions.questions_repo import QuestionRepository
from intric.roles.roles_repo import RolesRepository
from intric.roles.roles_service import RolesService
from intric.security_classifications.application.security_classification_service import (
    SecurityClassificationService,
)
from intric.security_classifications.domain.repositories.security_classification_repo_impl import (
    SecurityClassificationRepoImpl,
)
from intric.services.service_repo import ServiceRepository
from intric.services.service_runner import ServiceRunner
from intric.services.service_service import ServiceService
from intric.sessions.session_service import SessionService
from intric.sessions.sessions_repo import SessionRepository
from intric.settings.setting_service import SettingService
from intric.settings.settings_repo import SettingsRepository
from intric.spaces.api.space_assembler import SpaceAssembler
from intric.spaces.domain.resource_mover_service import ResourceMoverService
from intric.spaces.space_factory import SpaceFactory
from intric.spaces.space_init_service import SpaceInitService
from intric.spaces.space_repo import SpaceRepository
from intric.spaces.space_service import SpaceService
from intric.storage.application.storage_services import StorageInfoService
from intric.storage.domain.storage_factory import StorageInfoFactory
from intric.storage.domain.storage_repo import StorageInfoRepository
from intric.storage.presentation.storage_assembler import StorageInfoAssembler
from intric.templates.api.templates_assembler import TemplateAssembler
from intric.templates.app_template.api.app_template_assembler import (
    AppTemplateAssembler,
)
from intric.templates.app_template.app_template_factory import AppTemplateFactory
from intric.templates.app_template.app_template_repo import AppTemplateRepository
from intric.templates.app_template.app_template_service import AppTemplateService
from intric.templates.assistant_template.api.assistant_template_assembler import (
    AssistantTemplateAssembler,
)
from intric.templates.assistant_template.assistant_template_factory import (
    AssistantTemplateFactory,
)
from intric.templates.assistant_template.assistant_template_repo import (
    AssistantTemplateRepository,
)
from intric.templates.assistant_template.assistant_template_service import (
    AssistantTemplateService,
)
from intric.templates.templates_service import TemplateService
from intric.tenants.tenant import TenantInDB
from intric.tenants.tenant_repo import TenantRepository
from intric.tenants.tenant_service import TenantService
from intric.token_usage.application.token_usage_service import TokenUsageService
from intric.token_usage.infrastructure.token_usage_analyzer import TokenUsageAnalyzer
from intric.token_usage.infrastructure.user_token_usage_analyzer import (
    UserTokenUsageAnalyzer,
)
from intric.transcription_models.application import TranscriptionModelCRUDService
from intric.transcription_models.domain import TranscriptionModelRepository
from intric.transcription_models.domain.transcription_model_service import (
    TranscriptionModelService,
)
from intric.transcription_models.infrastructure import TranscriptionModelEnableService
from intric.user_groups.user_groups_repo import UserGroupsRepository
from intric.user_groups.user_groups_service import UserGroupsService
from intric.users.user import UserInDB
from intric.users.user_assembler import UserAssembler
from intric.users.user_repo import UsersRepository
from intric.users.user_service import UserService
from intric.websites.application.crawl_scheduler_service import CrawlSchedulerService
from intric.websites.application.website_crud_service import WebsiteCRUDService
from intric.websites.domain.crawl_run_repo import CrawlRunRepository
from intric.websites.domain.crawl_service import CrawlService
from intric.websites.domain.website_sparse_repo import WebsiteSparseRepository
from intric.websites.infrastructure.http_auth_encryption import (
    HttpAuthEncryptionService,
)
from intric.websites.infrastructure.update_website_size_service import (
    UpdateWebsiteSizeService,
)
from intric.websites.infrastructure.website_cleaner_service import WebsiteCleanerService
from intric.worker.task_manager import TaskManager
from intric.workflows.step_repo import StepRepository


class Container(containers.DeclarativeContainer):
    __self__ = providers.Self()

    # Configuration
    config = providers.Configuration()

    # Objects
    session = providers.Dependency(instance_of=AsyncSession)
    user = providers.Dependency(instance_of=UserInDB)
    tenant = providers.Dependency(instance_of=TenantInDB)
    aiohttp_client = providers.Object(aiohttp_client)

    # Factories
    prompt_factory = providers.Factory(PromptFactory)
    assistant_template_factory = providers.Factory(AssistantTemplateFactory)
    app_template_factory = providers.Factory(AppTemplateFactory)

    # App factory must be defined before it's used by the space factory
    app_factory = providers.Factory(
        AppFactory, app_template_factory=app_template_factory
    )

    # Assistant factory must be defined before it's used by the space factory
    assistant_factory = providers.Factory(
        AssistantFactory,
        prompt_factory=prompt_factory,
        assistant_template_factory=assistant_template_factory,
    )

    # Space factory now depends on assistant_factory and app_factory
    space_factory = providers.Factory(
        SpaceFactory,
        assistant_factory=assistant_factory,
        app_factory=app_factory,
    )

    storage_info_factory = providers.Factory(StorageInfoFactory)
    app_run_factory = providers.Factory(AppRunFactory)
    actor_factory = providers.Factory(ActorFactory)

    # Managers
    actor_manager = providers.Factory(ActorManager, user=user, factory=actor_factory)

    # Assemblers
    prompt_assembler = providers.Factory(PromptAssembler, user=user)
    assistant_assembler = providers.Factory(
        AssistantAssembler, user=user, prompt_assembler=prompt_assembler
    )
    group_chat_assembler = providers.Factory(GroupChatAssembler)
    completion_model_assembler = providers.Factory(CompletionModelAssembler)
    integration_knowledge_assembler = providers.Factory(IntegrationKnowledgeAssembler)
    space_assembler = providers.Factory(
        SpaceAssembler,
        user=user,
        assistant_assembler=assistant_assembler,
        completion_model_assembler=completion_model_assembler,
        actor_manager=actor_manager,
    )
    storage_assembler = providers.Factory(StorageInfoAssembler)
    app_assembler = providers.Factory(
        AppAssembler,
        prompt_assembler=prompt_assembler,
    )
    app_run_assembler = providers.Factory(AppRunAssembler)
    app_template_assembler = providers.Factory(AppTemplateAssembler)
    assistant_template_assembler = providers.Factory(AssistantTemplateAssembler)
    template_assembler = providers.Factory(
        TemplateAssembler,
        app_assembler=AppTemplateAssembler,
        assistant_assembler=AssistantTemplateAssembler,
    )

    user_assembler = providers.Factory(UserAssembler)

    confluence_content_assembler = providers.Factory(ConfluenceContentAssembler)
    integration_assembler = providers.Factory(IntegrationAssembler)
    tenant_integration_assembler = providers.Factory(TenantIntegrationAssembler)
    user_integration_assembler = providers.Factory(UserIntegrationAssembler)

    # Mappers for integration domain
    integration_mapper = providers.Factory(IntegrationMapper)
    tenant_integration_mapper = providers.Factory(TenantIntegrationMapper)
    user_integration_mapper = providers.Factory(UserIntegrationMapper)
    integration_knowledge_mapper = providers.Factory(IntegrationKnowledgeMapper)
    confluence_token_mapper = providers.Factory(OauthTokenMapper)

    # HTTP auth encryption service
    http_auth_encryption_service = providers.Factory(HttpAuthEncryptionService)

    # Repositories
    user_repo = providers.Factory(UsersRepository, session=session)
    tenant_repo = providers.Factory(TenantRepository, session=session)
    settings_repo = providers.Factory(SettingsRepository, session=session)
    tenant_repo = providers.Factory(TenantRepository, session=session)
    prompt_repo = providers.Factory(
        PromptRepository, session=session, factory=prompt_factory
    )

    api_key_repo = providers.Factory(ApiKeysRepository, session=session)
    group_repo = providers.Factory(GroupRepository, session=session)
    info_blob_repo = providers.Factory(InfoBlobRepository, session=session)
    job_repo = providers.Factory(JobRepository, session=session)
    allowed_origin_repo = providers.Factory(AllowedOriginRepository, session=session)
    predefined_roles_repo = providers.Factory(
        PredefinedRolesRepository, session=session
    )
    role_repo = providers.Factory(RolesRepository, session=session)
    completion_model_repo = providers.Factory(
        CompletionModelsRepository, session=session
    )
    # TODO: rename when the first repo is not used anymore
    completion_model_repo2 = providers.Factory(
        CompletionModelRepository, session=session, user=user
    )
    embedding_model_repo2 = providers.Factory(
        EmbeddingModelRepository, session=session, user=user
    )
    transcription_model_repo = providers.Factory(
        TranscriptionModelRepository, session=session, user=user
    )
    embedding_model_repo = providers.Factory(
        AdminEmbeddingModelsService, session=session
    )
    website_sparse_repo = providers.Factory(WebsiteSparseRepository, session=session)
    integration_knowledge_repo = providers.Factory(
        IntegrationKnowledgeRepoImpl,
        session=session,
        mapper=integration_knowledge_mapper,
        embedding_model_repo=embedding_model_repo2,
    )
    integration_repo = providers.Factory(
        IntegrationRepoImpl, session=session, mapper=integration_mapper
    )
    tenant_integration_repo = providers.Factory(
        TenantIntegrationRepoImpl, session=session, mapper=tenant_integration_mapper
    )
    user_integration_repo = providers.Factory(
        UserIntegrationRepoImpl, session=session, mapper=user_integration_mapper
    )
    oauth_token_repo = providers.Factory(
        OauthTokenRepoImpl, session=session, mapper=confluence_token_mapper
    )
    transcription_model_enable_service = providers.Factory(
        TranscriptionModelEnableService, session=session
    )
    assistant_repo = providers.Factory(
        AssistantRepository,
        session=session,
        factory=assistant_factory,
        completion_model_repo=completion_model_repo2,
    )

    info_blob_chunk_repo = providers.Factory(InfoBlobChunkRepo, session=session)

    step_repo = providers.Factory(StepRepository, session=session)
    user_groups_repo = providers.Factory(UserGroupsRepository, session=session)
    analysis_repo = providers.Factory(AnalysisRepository, session=session)
    session_repo = providers.Factory(SessionRepository, session=session)
    question_repo = providers.Factory(QuestionRepository, session=session)
    file_repo = providers.Factory(FileRepository, session=session)
    crawl_run_repo = providers.Factory(CrawlRunRepository, session=session)

    storage_repo = providers.Factory(
        StorageInfoRepository, user=user, session=session, factory=storage_info_factory
    )
    app_repo = providers.Factory(
        AppRepository,
        session=session,
        factory=app_factory,
        prompt_repo=prompt_repo,
        transcription_model_repo=transcription_model_repo,
    )
    app_run_repo = providers.Factory(
        AppRunRepository, session=session, factory=app_run_factory
    )
    service_repo = providers.Factory(
        ServiceRepository,
        session=session,
        completion_model_repo=completion_model_repo2,
    )
    space_repo = providers.Factory(
        SpaceRepository,
        user=user,
        factory=space_factory,
        session=session,
        app_repo=app_repo,
        assistant_repo=assistant_repo,
        completion_model_repo=completion_model_repo2,
        transcription_model_repo=transcription_model_repo,
        embedding_model_repo=embedding_model_repo2,
        http_auth_encryption=http_auth_encryption_service,
    )
    app_template_repo = providers.Factory(
        AppTemplateRepository, factory=app_template_factory, session=session
    )
    assistant_template_repo = providers.Factory(
        AssistantTemplateRepository, factory=assistant_template_factory, session=session
    )

    module_repo = providers.Factory(ModuleRepository, session=session)

    security_classification_repo = providers.Factory(
        SecurityClassificationRepoImpl,
        session=session,
        user=user,
    )

    # Completion model adapters
    context_builder = providers.Factory(ContextBuilder)
    completion_service = providers.Factory(
        CompletionService,
        context_builder=context_builder,
    )

    # Datastore
    create_embeddings_service = providers.Factory(CreateEmbeddingsService)
    datastore = providers.Factory(
        Datastore,
        user=user,
        create_embeddings_service=create_embeddings_service,
        info_blob_chunk_repo=info_blob_chunk_repo,
    )
    text_extractor = providers.Factory(TextExtractor)
    image_extractor = providers.Factory(ImageExtractor)

    # Services
    references_service = providers.Factory(
        ReferencesService,
        info_blobs_repo=info_blob_repo,
        datastore=datastore,
    )
    ai_models_service = providers.Factory(
        AIModelsService,
        user=user,
        embedding_model_repo=embedding_model_repo,
        completion_model_repo=completion_model_repo,
        tenant_repo=tenant_repo,
    )
    completion_model_crud_service = providers.Factory(
        CompletionModelCRUDService,
        user=user,
        completion_model_repo=completion_model_repo2,
        security_classification_repo=security_classification_repo,
    )
    transcription_model_crud_service = providers.Factory(
        TranscriptionModelCRUDService,
        user=user,
        transcription_model_repo=transcription_model_repo,
        security_classification_repo=security_classification_repo,
    )
    embedding_model_crud_service = providers.Factory(
        EmbeddingModelCRUDService,
        user=user,
        embedding_model_repo=embedding_model_repo2,
        security_classification_repo=security_classification_repo,
    )
    completion_model_service = providers.Factory(
        CompletionModelService,
        completion_model_repo=completion_model_repo2,
    )
    completion_model_usage_service = providers.Factory(
        CompletionModelUsageService,
        session=session,
        completion_model_repo=completion_model_repo2,
    )
    completion_model_migration_service = providers.Factory(
        CompletionModelMigrationService,
        session=session,
        completion_model_repo=completion_model_repo2,
        usage_service=completion_model_usage_service,
    )
    completion_model_migration_history_service = providers.Factory(
        CompletionModelMigrationHistoryService,
        session=session,
    )
    transcription_model_service = providers.Factory(
        TranscriptionModelService,
        transcription_model_repo=transcription_model_repo,
    )
    auth_service = providers.Factory(
        AuthService,
        api_key_repo=api_key_repo,
    )
    tenant_service = providers.Factory(
        TenantService,
        repo=tenant_repo,
        completion_model_repo=completion_model_repo,
        embedding_model_repo=embedding_model_repo,
        transcription_model_enable_service=transcription_model_enable_service,
    )
    user_service = providers.Factory(
        UserService,
        user_repo=user_repo,
        auth_service=auth_service,
        settings_repo=settings_repo,
        tenant_repo=tenant_repo,
        predefined_roles_repo=predefined_roles_repo,
        info_blob_repo=info_blob_repo,
    )
    security_classification_service = providers.Factory(
        SecurityClassificationService,
        user=user,
        repo=security_classification_repo,
        tenant_repo=tenant_repo,
    )
    space_service = providers.Factory(
        SpaceService,
        user=user,
        repo=space_repo,
        factory=space_factory,
        user_repo=user_repo,
        embedding_model_crud_service=embedding_model_crud_service,
        completion_model_crud_service=completion_model_crud_service,
        transcription_model_crud_service=transcription_model_crud_service,
        completion_model_service=completion_model_service,
        transcription_model_service=transcription_model_service,
        actor_manager=actor_manager,
        security_classification_service=security_classification_service,
    )
    storage_service = providers.Factory(StorageInfoService, repo=storage_repo)
    job_service = providers.Factory(
        JobService,
        user=user,
        job_repo=job_repo,
    )
    file_size_service = providers.Factory(
        FileSizeService,
    )
    task_service = providers.Factory(
        TaskService,
        user=user,
        file_size_service=file_size_service,
        job_service=job_service,
    )
    collection_crud_service = providers.Factory(
        CollectionCRUDService,
        user=user,
        space_service=space_service,
        space_repo=space_repo,
        actor_manager=actor_manager,
    )
    group_service = providers.Factory(
        GroupService,
        user=user,
        repo=group_repo,
        space_repo=space_repo,
        tenant_repo=tenant_repo,
        info_blob_repo=info_blob_repo,
        ai_models_service=ai_models_service,
        space_service=space_service,
        actor_manager=actor_manager,
        task_service=task_service,
    )
    quota_service = providers.Factory(
        QuotaService, user=user, info_blob_repo=info_blob_repo
    )
    allowed_origin_service = providers.Factory(
        AllowedOriginService,
        user=user,
        repo=allowed_origin_repo,
    )
    predefined_role_service = providers.Factory(
        PredefinedRolesService, repo=predefined_roles_repo
    )
    role_service = providers.Factory(RolesService, user=user, repo=role_repo)
    settings_service = providers.Factory(
        SettingService,
        user=user,
        repo=settings_repo,
        ai_models_service=ai_models_service,
    )
    crawl_service = providers.Factory(
        CrawlService, repo=crawl_run_repo, task_service=task_service
    )
    crawl_scheduler_service = providers.Factory(
        CrawlSchedulerService, website_sparse_repo=website_sparse_repo
    )
    update_website_size_service = providers.Factory(
        UpdateWebsiteSizeService,
        session=session,
    )
    website_cleaner_service = providers.Factory(
        WebsiteCleanerService,
        session=session,
    )
    website_crud_service = providers.Factory(
        WebsiteCRUDService,
        user=user,
        space_service=space_service,
        space_repo=space_repo,
        crawl_run_repo=crawl_run_repo,
        actor_manager=actor_manager,
        crawl_service=crawl_service,
    )
    info_blob_service = providers.Factory(
        InfoBlobService,
        repo=info_blob_repo,
        space_repo=space_repo,
        user=user,
        quota_service=quota_service,
        update_website_size_service=update_website_size_service,
        group_service=group_service,
        space_service=space_service,
        actor_manager=actor_manager,
    )
    prompt_service = providers.Factory(
        PromptService, user=user, repo=prompt_repo, factory=prompt_factory
    )
    file_protocol = providers.Factory(
        FileProtocol,
        file_size_service=file_size_service,
        text_extractor=text_extractor,
        image_extractor=image_extractor,
    )
    file_service = providers.Factory(
        FileService,
        user=user,
        repo=file_repo,
        protocol=file_protocol,
    )
    assistant_template_service = providers.Factory(
        AssistantTemplateService,
        repo=assistant_template_repo,
        factory=assistant_template_factory,
    )
    session_service = providers.Factory(
        SessionService,
        user=user,
        question_repo=question_repo,
        session_repo=session_repo,
    )
    resource_mover_service = providers.Factory(
        ResourceMoverService,
        space_repo=space_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )
    assistant_service = providers.Factory(
        AssistantService,
        user=user,
        repo=assistant_repo,
        space_repo=space_repo,
        auth_service=auth_service,
        service_repo=service_repo,
        step_repo=step_repo,
        completion_model_crud_service=completion_model_crud_service,
        space_service=space_service,
        factory=assistant_factory,
        prompt_service=prompt_service,
        file_service=file_service,
        assistant_template_service=assistant_template_service,
        session_service=session_service,
        actor_manager=actor_manager,
        integration_knowledge_repo=integration_knowledge_repo,
        completion_service=completion_service,
        references_service=references_service,
    )
    group_chat_service = providers.Factory(
        GroupChatService,
        user=user,
        space_service=space_service,
        space_repo=space_repo,
        actor_manager=actor_manager,
        assistant_service=assistant_service,
        session_service=session_service,
        completion_service=completion_service,
    )
    app_template_service = providers.Factory(
        AppTemplateService,
        repo=app_template_repo,
        factory=app_template_factory,
    )

    template_service = providers.Factory(
        TemplateService,
        app_service=app_template_service,
        assistant_service=assistant_template_service,
    )

    space_init_service = providers.Factory(
        SpaceInitService,
        user=user,
        space_service=space_service,
        assistant_service=assistant_service,
        space_repo=space_repo,
    )
    user_group_service = providers.Factory(
        UserGroupsService, user=user, repo=user_groups_repo
    )
    admin_service = providers.Factory(
        AdminService,
        user=user,
        user_repo=user_repo,
        tenant_repo=tenant_repo,
        user_service=user_service,
    )
    settings_service = providers.Factory(
        SettingService,
        user=user,
        repo=settings_repo,
        ai_models_service=ai_models_service,
    )
    service_service = providers.Factory(
        ServiceService,
        repo=service_repo,
        space_repo=space_repo,
        question_repo=question_repo,
        group_service=group_service,
        user=user,
        completion_model_crud_service=completion_model_crud_service,
        space_service=space_service,
        actor_manager=actor_manager,
    )
    limit_service = providers.Factory(LimitService)

    integration_service = providers.Factory(
        IntegrationService,
        integration_repo=integration_repo,
    )
    integration_knowledge_service = providers.Factory(
        IntegrationKnowledgeService,
        job_service=job_service,
        user=user,
        oauth_token_repo=oauth_token_repo,
        space_repo=space_repo,
        integration_knowledge_repo=integration_knowledge_repo,
        embedding_model_repo=embedding_model_repo2,
        user_integration_repo=user_integration_repo,
        actor_manager=actor_manager,
    )
    tenant_integration_service = providers.Factory(
        TenantIntegrationService,
        tenant_integration_repo=tenant_integration_repo,
        integration_repo=integration_repo,
        user=user,
    )
    user_integration_service = providers.Factory(
        UserIntegrationService,
        user_integration_repo=user_integration_repo,
        tenant_integration_repo=tenant_integration_repo,
        user=user,
    )
    confluence_auth_service = providers.Factory(ConfluenceAuthService)
    sharepoint_auth_service = providers.Factory(SharepointAuthService)
    oauth2_service = providers.Factory(
        Oauth2Service,
        confluence_auth_service=confluence_auth_service,
        tenant_integration_repo=tenant_integration_repo,
        user_integration_repo=user_integration_repo,
        oauth_token_repo=oauth_token_repo,
        sharepoint_auth_service=sharepoint_auth_service,
    )

    oauth_token_service = providers.Factory(
        OauthTokenService,
        oauth_token_repo=oauth_token_repo,
        confluence_auth_service=confluence_auth_service,
        sharepoint_auth_service=sharepoint_auth_service,
    )
    confluence_content_service = providers.Factory(
        ConfluenceContentService,
        oauth_token_repo=oauth_token_repo,
        job_service=job_service,
        user_integration_repo=user_integration_repo,
        user=user,
        oauth_token_service=oauth_token_service,
        datastore=datastore,
        info_blob_service=info_blob_service,
        integration_knowledge_repo=integration_knowledge_repo,
    )
    sharepoint_content_service = providers.Factory(
        SharePointContentService,
        oauth_token_repo=oauth_token_repo,
        job_service=job_service,
        user_integration_repo=user_integration_repo,
        user=user,
        oauth_token_service=oauth_token_service,
        datastore=datastore,
        info_blob_service=info_blob_service,
        integration_knowledge_repo=integration_knowledge_repo,
        session=session,
    )
    confluence_preview_service = providers.Factory(
        ConfluencePreviewService,
        oauth_token_service=oauth_token_service,
    )
    sharepoint_preview_service = providers.Factory(
        SharePointPreviewService,
        oauth_token_service=oauth_token_service,
    )
    integration_preview_service = providers.Factory(
        IntegrationPreviewService,
        oauth_token_repo=oauth_token_repo,
        user_integration_repo=user_integration_repo,
        confluence_preview_service=confluence_preview_service,
        sharepoint_preview_service=sharepoint_preview_service,
    )
    # Completion
    service_runner = providers.Factory(
        ServiceRunner,
        user=user,
        completion_service=completion_service,
        references_service=references_service,
        question_repo=question_repo,
        file_service=file_service,
    )
    analysis_service = providers.Factory(
        AnalysisService,
        user=user,
        repo=analysis_repo,
        assistant_service=assistant_service,
        session_repo=session_repo,
        question_repo=question_repo,
        space_service=space_service,
        session_service=session_service,
        group_chat_service=group_chat_service,
        completion_service=completion_service,
    )

    conversation_service = providers.Factory(
        ConversationService,
        assistant_service=assistant_service,
        group_chat_service=group_chat_service,
        session_service=session_service,
        completion_service=completion_service,
        space_service=space_service,
    )

    # Token Usage
    token_usage_analyzer = providers.Factory(
        TokenUsageAnalyzer,
        session=session,
    )
    user_token_usage_analyzer = providers.Factory(
        UserTokenUsageAnalyzer,
        session=session,
    )
    token_usage_service = providers.Factory(
        TokenUsageService,
        user=user,
        token_usage_analyzer=token_usage_analyzer,
        user_token_usage_analyzer=user_token_usage_analyzer,
    )

    # Worker
    task_manager = providers.Factory(
        TaskManager,
        user=user,
        session=session,
        job_service=job_service,
    )
    text_processor = providers.Factory(
        TextProcessor,
        user=user,
        extractor=text_extractor,
        datastore=datastore,
        info_blob_service=info_blob_service,
    )
    transcriber = providers.Factory(
        Transcriber,
        file_repo=file_repo,
    )
    crawler = providers.Factory(Crawler)

    # Worker dependent services
    app_service = providers.Factory(
        AppService,
        user=user,
        repo=app_repo,
        space_repo=space_repo,
        factory=app_factory,
        completion_model_crud_service=completion_model_crud_service,
        transcription_model_crud_service=transcription_model_crud_service,
        file_service=file_service,
        prompt_service=prompt_service,
        completion_service=completion_service,
        transcriber=transcriber,
        app_template_service=app_template_service,
        actor_manager=actor_manager,
    )
    app_run_service = providers.Factory(
        AppRunService,
        user=user,
        repo=app_run_repo,
        factory=app_run_factory,
        app_service=app_service,
        file_service=file_service,
        job_service=job_service,
    )

    data_retention_service = providers.Factory(
        DataRetentionService,
        session=session,
    )
