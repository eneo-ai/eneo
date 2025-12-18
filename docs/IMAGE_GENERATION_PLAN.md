# Implementation Plan: Image Generation for Eneo

## Summary

Add image generation capabilities following existing DDD patterns, with LiteLLM for multi-provider support, full multi-tenancy, and icon generation feature for assistants/apps/spaces.

**Key decisions:**
- LiteLLM-based for multi-provider support (DALL-E, Flux, Azure, etc.)
- Full tenant configuration (like other AI models)
- General service architecture (reusable beyond icons)
- Icon generation with 2-4 variants, auto-prompt with edit option
- Backend + Frontend implementation

---

## Phase 1: Database Layer

### 1.1 Create Database Tables

**File:** `backend/src/intric/database/tables/image_models_table.py`

```python
class ImageModels(BasePublic):
    name: Mapped[str]                    # Sync key (e.g., 'dall-e-3')
    nickname: Mapped[str]                # Display name
    family: Mapped[str]                  # 'openai', 'azure', etc.
    stability: Mapped[str]
    hosting: Mapped[str]
    description: Mapped[Optional[str]]
    org: Mapped[Optional[str]]
    is_deprecated: Mapped[bool]
    open_source: Mapped[Optional[bool]]
    max_resolution: Mapped[Optional[str]]
    supported_sizes: Mapped[Optional[list[str]]]     # ARRAY(String)
    supported_qualities: Mapped[Optional[list[str]]]
    max_images_per_request: Mapped[int]
    litellm_model_name: Mapped[Optional[str]]
    base_url: Mapped[Optional[str]]

class ImageModelSettings(BaseCrossReference):
    tenant_id: Mapped[UUID]              # PK, FK -> tenants
    image_model_id: Mapped[UUID]         # PK, FK -> image_models
    is_org_enabled: Mapped[bool]
    is_org_default: Mapped[bool]
    security_classification_id: Mapped[Optional[UUID]]

class GeneratedImages(BasePublic):
    tenant_id: Mapped[UUID]
    user_id: Mapped[Optional[UUID]]
    image_model_id: Mapped[Optional[UUID]]
    prompt: Mapped[str]
    revised_prompt: Mapped[Optional[str]]
    size: Mapped[Optional[str]]
    quality: Mapped[Optional[str]]
    blob: Mapped[bytes]                  # BYTEA
    mimetype: Mapped[str]
    file_size: Mapped[int]
    metadata: Mapped[Optional[dict]]     # JSONB
```

### 1.2 Create Migration

**File:** `backend/alembic/versions/YYYYMMDD_add_image_models.py`

- Create `image_models` table
- Create `image_model_settings` table
- Create `generated_images` table
- Add indexes on `tenant_id` and `created_at`

---

## Phase 2: Domain Layer

### 2.1 Create Domain Structure

```
backend/src/intric/image_models/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── image_model.py           # Domain entity extending AIModel
│   └── image_model_repo.py      # Repository interface
├── application/
│   ├── __init__.py
│   ├── image_model_crud_service.py     # CRUD operations
│   └── image_generation_service.py     # Core generation logic
├── infrastructure/
│   ├── __init__.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   └── litellm_image_adapter.py    # LiteLLM wrapper
│   └── generated_image_repo.py
└── presentation/
    ├── __init__.py
    ├── image_model_assembler.py
    ├── image_model_models.py    # Pydantic models
    └── image_models_router.py   # FastAPI router
```

### 2.2 Domain Entity

**File:** `backend/src/intric/image_models/domain/image_model.py`

Follow pattern from `transcription_models/domain/transcription_model.py`:

```python
class ImageModel(AIModel):
    # Extends AIModel with image-specific fields:
    max_resolution: Optional[str]
    supported_sizes: list[str]
    supported_qualities: list[str]
    max_images_per_request: int
    litellm_model_name: Optional[str]
    base_url: Optional[str]
    is_org_default: bool

    @classmethod
    def create_from_db(cls, image_model_db, settings, user): ...
```

### 2.3 Repository

**File:** `backend/src/intric/image_models/domain/image_model_repo.py`

Methods: `all()`, `one()`, `one_or_none()`, `update()`

---

## Phase 3: Infrastructure Layer

### 3.1 LiteLLM Image Adapter

**File:** `backend/src/intric/image_models/infrastructure/adapters/litellm_image_adapter.py`

```python
class LiteLLMImageAdapter:
    def __init__(self, model: ImageModel, credential_resolver: Optional[CredentialResolver]):
        # Get provider config from LiteLLMProviderRegistry
        # Handle tenant-specific credentials

    async def generate_images(
        self,
        prompt: str,
        n: int = 1,
        size: str = "1024x1024",
        quality: str = "standard",
    ) -> list[ImageGenerationResult]:
        # Call litellm.aimage_generation()
        # Handle response (url or b64_json)
        # Return results with blob data
```

### 3.2 Generated Image Repository

**File:** `backend/src/intric/image_models/infrastructure/generated_image_repo.py`

Methods: `save()`, `get_by_id()`, `list_by_tenant()`

---

## Phase 4: Application Layer

### 4.1 CRUD Service

**File:** `backend/src/intric/image_models/application/image_model_crud_service.py`

```python
class ImageModelCRUDService:
    async def get_image_models(self) -> list[ImageModel]
    async def get_available_image_models(self) -> list[ImageModel]
    async def get_default_image_model(self) -> Optional[ImageModel]
    @validate_permissions(Permission.ADMIN)
    async def update_image_model(self, model_id, is_org_enabled, is_org_default, security_classification)
```

### 4.2 Image Generation Service

**File:** `backend/src/intric/image_models/application/image_generation_service.py`

```python
class ImageGenerationService:
    """General-purpose image generation service."""

    async def generate_images(
        self,
        prompt: str,
        model_id: Optional[UUID] = None,
        n: int = 1,
        size: str = "1024x1024",
        quality: str = "standard",
        user_id: Optional[UUID] = None,
        save_to_db: bool = True,
    ) -> list[GeneratedImage]

    async def generate_icon_variants(
        self,
        resource_name: str,
        resource_description: Optional[str] = None,
        system_prompt: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        num_variants: int = 4,
    ) -> tuple[str, list[GeneratedImage]]:
        """Returns (generated_prompt, image_variants)"""

    def _generate_icon_prompt(self, name, description, system_prompt) -> str:
        """Auto-generate prompt from resource metadata."""
```

---

## Phase 5: Presentation Layer

### 5.1 API Models

**File:** `backend/src/intric/image_models/presentation/image_model_models.py`

- `ImageModelPublic` - Full model info with tenant settings
- `ImageModelUpdateFlags` - For admin updates
- `ImageGenerationRequest` - General generation request
- `IconGenerationRequest` - Icon-specific with resource metadata
- `IconGenerationResponse` - Prompt + base64 variants
- `ImageVariant` - index, blob_base64, mimetype

### 5.2 Router

**File:** `backend/src/intric/image_models/presentation/image_models_router.py`

Endpoints:
- `GET /` - List image models with tenant settings
- `POST /{id}/` - Update tenant settings (admin)
- `POST /generate` - Generate images from prompt
- `POST /generate-icon-variants` - Generate icon variants

---

## Phase 6: Configuration & Wiring

### 6.1 Update ai_models.yml

**File:** `backend/src/intric/server/dependencies/ai_models.yml`

Add `image_models:` section:

```yaml
image_models:
  - name: 'dall-e-3'
    nickname: 'DALL-E 3'
    family: 'openai'
    hosting: 'usa'
    org: OpenAI
    supported_sizes: ['1024x1024', '1792x1024', '1024x1792']
    supported_qualities: ['standard', 'hd']
    max_images_per_request: 1

  - name: 'dall-e-3-azure'
    nickname: 'DALL-E 3 (Azure)'
    family: 'azure'
    hosting: 'swe'
    litellm_model_name: 'azure/dall-e-3'
    # ... more config

  - name: 'gpt-image-1'
    nickname: 'GPT Image'
    family: 'openai'
    hosting: 'usa'
    supported_sizes: ['1024x1024', '1536x1024', '1024x1536', 'auto']
    max_images_per_request: 4
```

### 6.2 Update Container

**File:** `backend/src/intric/main/container/container.py`

Add providers for:
- `image_model_repo`
- `generated_image_repo`
- `image_model_assembler`
- `image_model_crud_service`
- `image_generation_service`

### 6.3 Register Router

**File:** `backend/src/intric/server/routers.py`

Add: `/api/v1/image-models` with tags=["Image Models"]

---

## Phase 7: Frontend Implementation

### 7.1 API Client (auto-generated)

Types will be generated from OpenAPI spec via `@intric/intric-js`

### 7.2 Icon Generator Component

**File:** `frontend/apps/web/src/lib/features/icons/IconGenerator.svelte`

Features:
- Button to open dialog
- Text area for prompt editing (pre-filled with auto-generated)
- "Regenerate" button
- 2x2 grid of variant images
- Click to select, confirm to use
- Dispatches `select` event with blob

### 7.3 Integrate with Existing Icon Upload

**Files to modify:**
- `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/settings/+page.svelte`
- `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/assistants/[assistantId]/edit/+page.svelte`
- `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/apps/[appId]/edit/+page.svelte`

Add IconGenerator alongside existing upload button, pass resource metadata.

### 7.4 Admin Panel for Image Models

**File:** `frontend/apps/web/src/routes/(app)/admin/image-models/+page.svelte`

Table with:
- Model name, provider, hosting
- Toggle for enabled
- Button for set as default
- Security classification selector

---

## Phase 8: Translations

### 8.1 Swedish (`messages/sv.json`)

```json
"generate_icon": "Generera ikon",
"generate_icon_title": "Generera ikon med AI",
"icon_prompt_label": "Beskriv ikonen",
"regenerate": "Generera igen",
"generating_icons": "Genererar ikoner...",
"use_selected_icon": "Använd vald ikon"
```

### 8.2 English (`messages/en.json`)

```json
"generate_icon": "Generate icon",
"generate_icon_title": "Generate icon with AI",
"icon_prompt_label": "Describe the icon",
"regenerate": "Regenerate",
"generating_icons": "Generating icons...",
"use_selected_icon": "Use selected icon"
```

---

## Phase 9: Cleanup & Testing

### 9.1 Remove Old PoC

**Delete:** `backend/src/intric/vision_models/` (entire directory)

The old FluxAdapter is hardcoded and doesn't follow DDD. New implementation replaces it completely.

### 9.2 Update Completion Service

**File:** `backend/src/intric/completion_models/infrastructure/completion_service.py`

Update `_handle_tool_call` to use new `ImageGenerationService` instead of old FluxAdapter.

### 9.3 Tests

- `tests/unittests/image_models/test_image_model_crud_service.py`
- `tests/unittests/image_models/test_image_generation_service.py`
- `tests/integration/image_models/test_litellm_adapter.py` (marked integration)

---

## Critical Files Summary

| Purpose | File Path |
|---------|-----------|
| DB Tables | `backend/src/intric/database/tables/image_models_table.py` |
| Domain Entity | `backend/src/intric/image_models/domain/image_model.py` |
| LiteLLM Adapter | `backend/src/intric/image_models/infrastructure/adapters/litellm_image_adapter.py` |
| Generation Service | `backend/src/intric/image_models/application/image_generation_service.py` |
| API Router | `backend/src/intric/image_models/presentation/image_models_router.py` |
| Config | `backend/src/intric/server/dependencies/ai_models.yml` |
| Container | `backend/src/intric/main/container/container.py` |
| Frontend Component | `frontend/apps/web/src/lib/features/icons/IconGenerator.svelte` |

## Reference Files (Patterns to Follow)

| Purpose | File Path |
|---------|-----------|
| Domain Entity Pattern | `backend/src/intric/transcription_models/domain/transcription_model.py` |
| DB Table Pattern | `backend/src/intric/database/tables/ai_models_table.py` |
| Icon Service | `backend/src/intric/icons/icon_service.py` |
| Embedding Adapter | `backend/src/intric/embedding_models/infrastructure/adapters/litellm_embeddings.py` |

---

## Implementation Order

1. **Phase 1** - Database (no dependencies)
2. **Phase 2** - Domain (depends on Phase 1)
3. **Phase 3** - Infrastructure (depends on Phase 2)
4. **Phase 4** - Application (depends on Phases 2, 3)
5. **Phase 5** - Presentation (depends on Phase 4)
6. **Phase 6** - Configuration (depends on Phase 5)
7. **Phase 7** - Frontend (depends on Phase 6)
8. **Phase 8** - Translations (depends on Phase 7)
9. **Phase 9** - Cleanup & Tests (after all phases)
