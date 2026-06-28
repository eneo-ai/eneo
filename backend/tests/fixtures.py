from uuid import uuid4

from eneo.ai_models.completion_models.completion_model import (
    CompletionModel,
)
from eneo.ai_models.embedding_models.embedding_model import (
    EmbeddingModelLegacy,
)
from eneo.assistants.assistant import Assistant
from eneo.authentication.auth_models import ApiKey
from eneo.collections.domain.collection import Collection
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB

TEST_UUID = uuid4()

TEST_EMBEDDING_MODEL = EmbeddingModelLegacy(
    id=uuid4(),
    name="text-embedding-3-small-test",
    family="openai",
    open_source=False,
    dimensions=512,
    max_input=8191,
    stability="stable",
    hosting="usa",
    is_deprecated=False,
)

TEST_EMBEDDING_MODEL_ADA = EmbeddingModelLegacy(
    id=uuid4(),
    name="text-embedding-ada-002-test",
    family="openai",
    open_source=False,
    max_input=8191,
    stability="stable",
    hosting="usa",
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
    family="openai",
    max_input_tokens=4000,
    max_output_tokens=1000,
    is_deprecated=False,
    stability="stable",
    hosting="usa",
    vision=True,
    reasoning=False,
)

TEST_MODEL_CHATGPT = CompletionModel(
    id=uuid4(),
    name="gpt-3.5-turbo",
    nickname="ChatGPT",
    family="openai",
    max_input_tokens=16385,
    max_output_tokens=4096,
    is_deprecated=False,
    stability="stable",
    hosting="usa",
    vision=False,
    reasoning=False,
)


TEST_MODEL_MIXTRAL = CompletionModel(
    id=uuid4(),
    name="Mixtral",
    nickname="Mixtral",
    family="mistral",
    max_input_tokens=16384,
    max_output_tokens=4096,
    is_deprecated=True,
    stability="experimental",
    hosting="eu",
    vision=False,
    reasoning=False,
)

TEST_MODEL_EU = CompletionModel(
    id=uuid4(),
    name="Mixtral",
    nickname="Mixtral",
    family="mistral",
    max_input_tokens=16384,
    max_output_tokens=4096,
    is_deprecated=False,
    stability="experimental",
    hosting="eu",
    vision=False,
    reasoning=False,
)

TEST_MODEL_AZURE = CompletionModel(
    id=uuid4(),
    name="azure model",
    nickname="azure model",
    family="azure",
    max_input_tokens=128000,
    max_output_tokens=4096,
    is_deprecated=False,
    stability="stable",
    hosting="usa",
    vision=True,
    reasoning=False,
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
