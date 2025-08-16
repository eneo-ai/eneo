from uuid import uuid4

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
    CompletionModelFamily,
    ModelHostingLocation,
    ModelStability,
)
from intric.ai_models.model_enums import ModelOrg
from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelFamily,
    EmbeddingModelLegacy,
)
from intric.assistants.assistant import Assistant
from intric.authentication.auth_models import ApiKey
from intric.collections.domain.collection import Collection
from intric.roles.permissions import Permission
from intric.roles.role import RoleInDB
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB

TEST_UUID = uuid4()

TEST_EMBEDDING_MODEL = EmbeddingModelLegacy(
    id=uuid4(),
    name="text-embedding-3-small-test",
    family=EmbeddingModelFamily.OPEN_AI,
    open_source=False,
    dimensions=512,
    max_input=8191,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    is_deprecated=False,
)

TEST_EMBEDDING_MODEL_ADA = EmbeddingModelLegacy(
    id=uuid4(),
    name="text-embedding-ada-002-test",
    family=EmbeddingModelFamily.OPEN_AI,
    open_source=False,
    max_input=8191,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    is_deprecated=False,
)

TEST_TENANT = TenantInDB(
    id=uuid4(),
    name="test_tenant",
    quota_limit=1024**3,
)
TEST_TENANT_2 = TenantInDB(
    id=uuid4(),
    name="test_tenant_2",
    quota_limit=1024**3,
)
TEST_API_KEY = ApiKey(key="supersecret", truncated_key="cret")
TEST_ROLE = RoleInDB(
    id=uuid4(),
    name="God",
    permissions=[permission for permission in Permission],
    tenant_id=TEST_TENANT.id,
)
TEST_USER = UserInDB(
    id=uuid4(),
    username="test_user",
    email="test@user.com",
    salt="test_salt",
    password="test_pass",
    used_tokens=0,
    tenant_id=TEST_TENANT.id,
    quota_limit=20000,
    tenant=TEST_TENANT,
    user_groups=[],
    roles=[TEST_ROLE],
    state="active",
)


TEST_USER_2 = UserInDB(
    id=uuid4(),
    username="test_user_3",
    email="test3@user.com",
    salt="test_salt",
    password="test_pass",
    used_tokens=0,
    tenant_id=TEST_TENANT_2.id,
    tenant=TEST_TENANT_2,
    roles=[TEST_ROLE],
    state="active",
)
TEST_MODEL_GPT4 = CompletionModel(
    id=uuid4(),
    name="gpt-4-turbo",
    nickname="GPT-4",
    family=CompletionModelFamily.OPEN_AI,
    token_limit=4000,
    is_deprecated=False,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    vision=True,
    reasoning=False,
)

TEST_MODEL_CHATGPT = CompletionModel(
    id=uuid4(),
    name="gpt-3.5-turbo",
    nickname="ChatGPT",
    family=CompletionModelFamily.OPEN_AI,
    token_limit=16385,
    is_deprecated=False,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    vision=False,
    reasoning=False,
)


TEST_MODEL_MIXTRAL = CompletionModel(
    id=uuid4(),
    name="Mixtral",
    nickname="Mixtral",
    family=CompletionModelFamily.MISTRAL,
    token_limit=16384,
    is_deprecated=True,
    stability=ModelStability.EXPERIMENTAL,
    hosting=ModelHostingLocation.EU,
    vision=False,
    reasoning=False,
)

TEST_MODEL_EU = CompletionModel(
    id=uuid4(),
    name="Mixtral",
    nickname="Mixtral",
    family=CompletionModelFamily.MISTRAL,
    token_limit=16384,
    is_deprecated=False,
    stability=ModelStability.EXPERIMENTAL,
    hosting=ModelHostingLocation.EU,
    vision=False,
    reasoning=False,
)

TEST_MODEL_AZURE = CompletionModel(
    id=uuid4(),
    name="azure model",
    nickname="azure model",
    family=CompletionModelFamily.AZURE,
    token_limit=128000,
    is_deprecated=False,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    vision=True,
    reasoning=False,
)

TEST_MODEL_GEMINI_FLASH = CompletionModel(
    id=uuid4(),
    name="gemini-2.5-flash",
    nickname="Gemini 2.5 Flash",
    family=CompletionModelFamily.GEMINI,
    token_limit=1048576,
    is_deprecated=False,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    vision=True,
    reasoning=True,
    user=TEST_USER,
    created_at=None,
    updated_at=None,
    description="Google's advanced reasoning model with optional thinking mode",
    nr_billion_parameters=None,
    hf_link=None,
    deployment_name=None,
    is_org_enabled=False,
    is_org_default=False,
    base_url=None,
    security_classification=None,
    org=ModelOrg.GOOGLE,
    open_source=False,
)

TEST_MODEL_GEMINI_PRO = CompletionModel(
    id=uuid4(),
    name="gemini-2.5-pro",
    nickname="Gemini 2.5 Pro",
    family=CompletionModelFamily.GEMINI,
    token_limit=1048576,
    is_deprecated=False,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    vision=True,
    reasoning=True,
    user=TEST_USER,
    created_at=None,
    updated_at=None,
    description="Google's most capable reasoning model with always-on thinking mode",
    nr_billion_parameters=None,
    hf_link=None,
    deployment_name=None,
    is_org_enabled=False,
    is_org_default=False,
    base_url=None,
    security_classification=None,
    org=ModelOrg.GOOGLE,
    open_source=False,
)

TEST_MODEL_GEMINI_FLASH_LITE = CompletionModel(
    id=uuid4(),
    name="gemini-2.5-flash-lite",
    nickname="Gemini 2.5 Flash-Lite",
    family=CompletionModelFamily.GEMINI,
    token_limit=1048576,
    is_deprecated=False,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    vision=True,
    reasoning=True,
    user=TEST_USER,
    created_at=None,
    updated_at=None,
    description="Google's most cost-efficient model supporting high throughput with reasoning",
    nr_billion_parameters=None,
    hf_link=None,
    deployment_name=None,
    is_org_enabled=False,
    is_org_default=False,
    base_url=None,
    security_classification=None,
    org=ModelOrg.GOOGLE,
    open_source=False,
)

TEST_MODEL_GEMINI_2_0_FLASH = CompletionModel(
    id=uuid4(),
    name="gemini-2.0-flash",
    nickname="Gemini 2.0 Flash",
    family=CompletionModelFamily.GEMINI,
    token_limit=1048576,
    is_deprecated=False,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    vision=True,
    reasoning=False,
    user=TEST_USER,
    created_at=None,
    updated_at=None,
    description="Google's next generation model with improved speed and capabilities",
    nr_billion_parameters=None,
    hf_link=None,
    deployment_name=None,
    is_org_enabled=False,
    is_org_default=False,
    base_url=None,
    security_classification=None,
    org=ModelOrg.GOOGLE,
    open_source=False,
)

TEST_MODEL_GEMINI_2_0_FLASH_LITE = CompletionModel(
    id=uuid4(),
    name="gemini-2.0-flash-lite",
    nickname="Gemini 2.0 Flash-Lite",
    family=CompletionModelFamily.GEMINI,
    token_limit=1048576,
    is_deprecated=False,
    stability=ModelStability.STABLE,
    hosting=ModelHostingLocation.USA,
    vision=True,
    reasoning=False,
    user=TEST_USER,
    created_at=None,
    updated_at=None,
    description="Google's cost-efficient model optimized for low latency",
    nr_billion_parameters=None,
    hf_link=None,
    deployment_name=None,
    is_org_enabled=False,
    is_org_default=False,
    base_url=None,
    security_classification=None,
    org=ModelOrg.GOOGLE,
    open_source=False,
)
TEST_COLLECTION = Collection.create(
    space_id=TEST_UUID,
    name="test_collection",
    embedding_model=TEST_EMBEDDING_MODEL,
    user=TEST_USER,
)


TEST_ASSISTANT = Assistant(
    id=uuid4(),
    space_id=TEST_UUID,
    name="test_assistant",
    prompt="test_prompt",
    completion_model=TEST_MODEL_CHATGPT,
    completion_model_kwargs={},
    user=TEST_USER,
    logging_enabled=False,
    websites=[],
    collections=[TEST_COLLECTION],
    attachments=[],
    published=False,
)
