# vLLM Integration in Eneo

## Overview

**Purpose**: This document explains how Eneo integrates with vLLM (Very Large Language Model) servers for completion and embedding models.

**Target Audience**: LLM systems that need to understand Eneo's vLLM integration architecture and requirements.

**Key Concept**: Eneo treats vLLM as an OpenAI API-compatible provider, using the AsyncOpenAI client with custom authentication headers and base URLs.

---

## Architecture Summary

### Multi-Tenant Design
- Eneo supports **per-tenant vLLM credentials** for isolated, multi-tenant deployments
- Each tenant can have their own vLLM endpoint and API key
- Prevents billing confusion and data leakage between tenants
- Falls back to global configuration in single-tenant mode

### OpenAI Compatibility Layer
- vLLM exposes OpenAI-compatible API endpoints
- Eneo uses the `openai` Python SDK (`AsyncOpenAI` client) to communicate with vLLM
- The `VLMMModelAdapter` extends `OpenAIModelAdapter` to leverage existing OpenAI integration code
- Authentication uses custom `X-API-Key` header instead of standard OpenAI authentication

---

## Credential Configuration

### Required Fields
When configuring vLLM in Eneo, **both** of the following fields are **mandatory**:

1. **`api_key`** (string, minimum 8 characters)
   - The API key for authenticating with the vLLM server
   - Stored encrypted at rest using Fernet encryption
   - Passed to vLLM via the `X-API-Key` HTTP header

2. **`endpoint`** (string, URL format)
   - The base URL of the vLLM server (e.g., `http://tenant-vllm:8000`)
   - Used as the `base_url` parameter for the AsyncOpenAI client
   - Must be accessible from the Eneo backend server

### Configuration Methods

#### Method 1: Tenant-Specific Credentials (Recommended for Multi-Tenant)
Use the Eneo Credentials API to set per-tenant vLLM configuration:

```http
PUT /api/v1/tenants/{tenant_id}/credentials/vllm
Authorization: Bearer {super_api_key}
Content-Type: application/json

{
  "api_key": "your-vllm-api-key-here",
  "endpoint": "http://tenant-vllm:8000"
}
```

**Response:**
```json
{
  "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
  "provider": "vllm",
  "masked_key": "...key",
  "encryption_status": "encrypted",
  "set_at": "2025-01-15T10:30:00Z"
}
```

**Requirements:**
- Requires `TENANT_CREDENTIALS_ENABLED=true` in Eneo configuration
- Requires `ENCRYPTION_KEY` environment variable to be set for credential encryption
- Requires super API key authentication
- Credentials are encrypted at rest and decrypted on demand

#### Method 2: Global Configuration (Single-Tenant Fallback)
Set global vLLM credentials via environment variables:

```bash
VLLM_API_KEY=your-global-vllm-api-key
VLLM_MODEL_URL=http://vllm-server:8000
```

**Note**: Global configuration is only used when:
- `TENANT_CREDENTIALS_ENABLED=false` (single-tenant mode), OR
- `TENANT_CREDENTIALS_ENABLED=true` AND the specific tenant has no vLLM credentials configured AND strict mode is disabled

---

## Configuration Modes

### Strict Multi-Tenant Mode
**Trigger**: `TENANT_CREDENTIALS_ENABLED=true`

**Behavior**:
- Each tenant **must** configure their own vLLM credentials
- No fallback to global `VLLM_API_KEY` or `VLLM_MODEL_URL`
- Raises error if tenant attempts to use vLLM without credentials
- Prevents accidental billing to shared infrastructure
- Ensures complete tenant isolation

**Error Message Example**:
```
No vLLM credentials found for tenant {tenant_id}.
Please configure via: PUT /api/v1/tenants/{tenant_id}/credentials/vllm
```

### Single-Tenant Mode
**Trigger**: `TENANT_CREDENTIALS_ENABLED=false`

**Behavior**:
- Checks tenant-specific credentials first
- Falls back to global environment variables if tenant credentials not found
- Suitable for single-organization deployments
- Simpler configuration management

---

## How Eneo Communicates with vLLM

### Client Initialization

**File**: `backend/src/intric/completion_models/infrastructure/adapters/vllm_model_adapter.py`

```python
from openai import AsyncOpenAI

# Initialize AsyncOpenAI client with vLLM base URL
client = AsyncOpenAI(
    api_key="EMPTY",  # Placeholder - actual key sent via header
    base_url="http://tenant-vllm:8000"  # vLLM endpoint
)

# API key passed via custom header for vLLM
extra_headers = {
    "X-API-Key": "actual-vllm-api-key-here"
}
```

**Key Points**:
- The `api_key` parameter in `AsyncOpenAI()` is set to `"EMPTY"` (placeholder)
- The actual API key is passed via the `X-API-Key` header in `extra_headers`
- The `base_url` points to the vLLM server endpoint
- This pattern allows vLLM to use custom authentication while maintaining OpenAI SDK compatibility

### Endpoint Resolution Priority

When determining which vLLM endpoint to use, Eneo follows this priority order:

1. **Tenant-specific endpoint** (if multi-tenant mode enabled and tenant has credentials)
2. **Model-specific base_url** (if defined in the model configuration)
3. **Global `VLLM_MODEL_URL`** environment variable (fallback)

**Code Logic**:
```python
# Priority 1: Tenant-specific
tenant_endpoint = credential_resolver.get_credential_field(
    provider="vllm",
    field="endpoint",
    required=True  # in strict mode
)

# Priority 2 & 3: Model-specific or global
base_url = next(
    (url for url in [tenant_endpoint, model.base_url, settings.vllm_model_url] if url),
    None
)
```

### API Call Pattern

**Completions Request**:
```python
async def get_response(client, model_name, messages, model_kwargs, extra_headers):
    response = await client.chat.completions.create(
        model=model_name,
        messages=messages,
        extra_headers=extra_headers,  # {"X-API-Key": api_key}
        stream=False,
        **model_kwargs  # temperature, max_tokens, etc.
    )
    return response
```

**Expected vLLM Endpoint**: `POST /v1/chat/completions`

---

## Request/Response Formats

### Chat Completion Request

**Endpoint**: `POST /v1/chat/completions`

**Headers**:
```http
Content-Type: application/json
X-API-Key: your-vllm-api-key
```

**Request Body** (OpenAI-compatible format):
```json
{
  "model": "mistral-7b-instruct",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "What is the capital of France?"
    }
  ],
  "temperature": 0.7,
  "max_tokens": 512,
  "stream": false
}
```

**Response Body**:
```json
{
  "id": "cmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "mistral-7b-instruct",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The capital of France is Paris."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 8,
    "total_tokens": 33
  }
}
```

### Streaming Completion Request

**Request Body** (with streaming enabled):
```json
{
  "model": "mistral-7b-instruct",
  "messages": [...],
  "stream": true,
  "stream_options": {
    "include_usage": true
  }
}
```

**Streaming Response** (Server-Sent Events format):
```
data: {"id":"cmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"mistral-7b-instruct","choices":[{"index":0,"delta":{"role":"assistant","content":"The"},"finish_reason":null}]}

data: {"id":"cmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"mistral-7b-instruct","choices":[{"index":0,"delta":{"content":" capital"},"finish_reason":null}]}

data: {"id":"cmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"mistral-7b-instruct","choices":[{"index":0,"delta":{"content":" of"},"finish_reason":null}]}

data: [DONE]
```

**Note**: The final chunk should include usage statistics when `stream_options.include_usage` is `true`.

### Embeddings Request (via LiteLLM)

**Endpoint**: `POST /v1/embeddings`

**Request Body**:
```json
{
  "input": [
    "This is the first text to embed.",
    "This is the second text to embed."
  ],
  "model": "bge-large-en-v1.5"
}
```

**Response Body**:
```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "index": 0,
      "embedding": [0.123, -0.456, 0.789, ...]
    },
    {
      "object": "embedding",
      "index": 1,
      "embedding": [0.321, -0.654, 0.987, ...]
    }
  ],
  "model": "bge-large-en-v1.5",
  "usage": {
    "prompt_tokens": 20,
    "total_tokens": 20
  }
}
```

---

## Error Handling

### Retry Logic

Eneo implements **exponential backoff retry** for vLLM API calls:

- **Maximum attempts**: 3
- **Wait time**: Random exponential backoff between 1-20 seconds
- **Retryable errors**: Authentication errors, rate limits, generic API errors
- **Non-retryable errors**: Bad request errors (invalid parameters)

**Implementation**:
```python
from tenacity import retry, wait_random_exponential, stop_after_attempt, retry_if_not_exception_type

@retry(
    wait=wait_random_exponential(min=1, max=20),
    stop=stop_after_attempt(3),
    retry=retry_if_not_exception_type(BadRequestException),
    reraise=True,
)
async def get_response(...):
    # API call logic
```

### Error Mapping

| OpenAI SDK Exception | Eneo Exception | Retry? | Meaning |
|---------------------|----------------|--------|---------|
| `openai.AuthenticationError` | `OpenAIException` | Yes | Invalid API key or unauthorized |
| `openai.RateLimitError` | `OpenAIException` | Yes | Rate limit exceeded |
| `openai.PermissionDeniedError` | `OpenAIException` | Yes | Permission denied (check firewall) |
| `openai.BadRequestError` | `BadRequestException` | No | Invalid request parameters |
| `openai.APIError` | `OpenAIException` | Yes | Generic API error |

### Common Error Scenarios

#### 1. Missing Tenant Credentials (Strict Mode)
**Error**:
```
No vLLM credentials found for tenant {tenant_id}.
Please configure via: PUT /api/v1/tenants/{tenant_id}/credentials/vllm
```

**Solution**: Configure tenant-specific vLLM credentials using the Credentials API.

#### 2. Authentication Error
**Error**:
```
Authentication error: Invalid API credentials. Please check your API key.
```

**Solution**: Verify the `api_key` configured for vLLM is correct and valid.

#### 3. Connection Error
**Error**:
```
Failed to connect to vLLM endpoint: http://tenant-vllm:8000
```

**Solution**: Verify the vLLM server is running and accessible from the Eneo backend. Check network connectivity and firewall rules.

---

## What vLLM Servers Must Provide

For Eneo to successfully integrate with a vLLM server, the server **must** provide:

### 1. OpenAI-Compatible API Endpoints

#### `/v1/chat/completions` (Required)
- Accept `POST` requests with OpenAI chat completion format
- Support `messages` array with `role` and `content` fields
- Support model parameters: `temperature`, `max_tokens`, `top_p`, etc.
- Return OpenAI-compatible response format with `choices` and `usage` fields

#### `/v1/embeddings` (Required for Embedding Models)
- Accept `POST` requests with OpenAI embedding format
- Support `input` field (string or array of strings)
- Return OpenAI-compatible response with `data` array of embeddings
- Include `usage` statistics in response

### 2. Authentication Support

#### `X-API-Key` Header Authentication
- Accept and validate API keys passed via `X-API-Key` HTTP header
- Return `401 Unauthorized` for invalid or missing keys
- Support multiple API keys for multi-tenant scenarios (recommended)

**Example Request**:
```http
POST /v1/chat/completions HTTP/1.1
Host: tenant-vllm:8000
Content-Type: application/json
X-API-Key: tenant-specific-api-key-here

{...request body...}
```

### 3. Streaming Support

#### Server-Sent Events (SSE) for Streaming
- Support `stream: true` parameter in completion requests
- Return streaming responses in Server-Sent Events format
- Each chunk should be a valid JSON object prefixed with `data: `
- Include final `data: [DONE]` message to signal stream completion
- Support `stream_options.include_usage` to return usage stats in final chunk

### 4. Error Responses

#### Standard HTTP Status Codes
- `200 OK`: Successful request
- `400 Bad Request`: Invalid parameters
- `401 Unauthorized`: Invalid or missing API key
- `403 Forbidden`: Valid key but insufficient permissions
- `429 Too Many Requests`: Rate limit exceeded
- `500 Internal Server Error`: Server-side error
- `503 Service Unavailable`: Server overloaded or down

#### OpenAI-Compatible Error Format
```json
{
  "error": {
    "message": "Invalid API key provided",
    "type": "invalid_request_error",
    "code": "invalid_api_key"
  }
}
```

### 5. Model Management

#### Model Name Handling
- Accept model names in requests (e.g., `"model": "mistral-7b-instruct"`)
- Return the same model name in responses
- Support multiple models if needed (multi-model deployment)

---

## Configuration Validation

### Provider Field Validation

**File**: `backend/src/intric/tenants/provider_field_config.py`

Eneo validates vLLM credentials against these rules:

```python
PROVIDER_REQUIRED_FIELDS = {
    "vllm": {"api_key", "endpoint"}  # Both fields are required
}
```

**Validation Rules**:
1. **`api_key`**: Minimum 8 characters, cannot be empty
2. **`endpoint`**: Must be a valid URL string, cannot be empty
3. **Provider name**: Case-insensitive (e.g., `"vllm"` or `"VLLM"` both accepted)

### Encryption Requirements

When `TENANT_CREDENTIALS_ENABLED=true`:
- `ENCRYPTION_KEY` environment variable **must** be set
- Credentials are encrypted using Fernet symmetric encryption
- Encryption key must be 32 URL-safe base64-encoded bytes
- Example: `ENCRYPTION_KEY=your-32-byte-base64-encoded-key-here`

---

## Database Schema

### Credentials Storage

**Table**: `tenants`
**Column**: `api_credentials` (JSONB type)

**Structure**:
```json
{
  "vllm": {
    "api_key": "encrypted_base64_string",
    "endpoint": "http://tenant-vllm:8000"
  },
  "openai": {
    "api_key": "encrypted_base64_string"
  }
}
```

**Indexes**:
- GIN index on `api_credentials` for efficient JSONB queries: `idx_tenants_api_credentials_gin`

**Constraints**:
- NOT NULL with default `'{}'::jsonb`
- Each provider can have arbitrary key-value pairs
- Required fields validated at application layer (not database constraints)

---

## Example Integration Flow

### Complete Flow: Setting Up vLLM for a Tenant

**Step 1**: Deploy vLLM server
```bash
# Example: Run vLLM with Mistral-7B model
docker run -d \
  --name tenant-vllm \
  -p 8000:8000 \
  --gpus all \
  vllm/vllm-openai:latest \
  --model mistralai/Mistral-7B-Instruct-v0.2 \
  --api-key your-vllm-api-key
```

**Step 2**: Configure tenant credentials in Eneo
```bash
curl -X PUT "http://eneo-api:8080/api/v1/tenants/550e8400-e29b-41d4-a716-446655440000/credentials/vllm" \
  -H "Authorization: Bearer super-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "your-vllm-api-key",
    "endpoint": "http://tenant-vllm:8000"
  }'
```

**Step 3**: Verify credentials stored
```bash
curl -X GET "http://eneo-api:8080/api/v1/tenants/550e8400-e29b-41d4-a716-446655440000/credentials" \
  -H "Authorization: Bearer super-api-key"
```

**Expected Response**:
```json
{
  "credentials": [
    {
      "provider": "vllm",
      "masked_key": "...key",
      "fields_set": ["api_key", "endpoint"],
      "encryption_status": "encrypted",
      "set_at": "2025-01-15T10:30:00Z"
    }
  ]
}
```

**Step 4**: Use vLLM model in Eneo
- Create a model in Eneo with `model_family: "vllm"`
- The model will automatically use the configured tenant credentials
- Eneo will route requests to `http://tenant-vllm:8000/v1/chat/completions`

---

## Summary for LLM Understanding

### Key Takeaways

1. **vLLM is treated as OpenAI-compatible**: Eneo uses the OpenAI Python SDK to communicate with vLLM servers

2. **Authentication via X-API-Key header**: Unlike standard OpenAI authentication, vLLM API keys are passed via the `X-API-Key` HTTP header

3. **Two required fields**: `api_key` and `endpoint` must both be configured for each tenant (in multi-tenant mode)

4. **Multi-tenant isolation**: Each tenant can have separate vLLM credentials to prevent data leakage and billing confusion

5. **Endpoint resolution priority**: Tenant-specific → Model-specific → Global configuration

6. **Retry logic**: Exponential backoff with 3 attempts for transient errors

7. **vLLM server requirements**:
   - OpenAI-compatible `/v1/chat/completions` and `/v1/embeddings` endpoints
   - `X-API-Key` header authentication support
   - Streaming support via Server-Sent Events
   - Standard HTTP error codes and OpenAI error format

### Expected vLLM Server Behavior

A compatible vLLM server must:
- ✅ Accept OpenAI-format requests at `/v1/chat/completions`
- ✅ Authenticate using `X-API-Key` header
- ✅ Return OpenAI-format responses with `choices` and `usage` fields
- ✅ Support streaming with `stream: true` parameter
- ✅ Return proper HTTP status codes (401, 429, 500, etc.)
- ✅ Include usage statistics in responses

---

## Reference Implementation Files

| Component | File Path | Purpose |
|-----------|-----------|---------|
| vLLM Adapter | `/backend/src/intric/completion_models/infrastructure/adapters/vllm_model_adapter.py` | Main vLLM integration logic |
| Credentials API | `/backend/src/intric/tenants/presentation/tenant_credentials_router.py` | API endpoints for credential management |
| Credential Resolver | `/backend/src/intric/settings/credential_resolver.py` | Resolves and decrypts credentials |
| Provider Config | `/backend/src/intric/tenants/provider_field_config.py` | Defines required fields for vLLM |
| OpenAI Response Handler | `/backend/src/intric/completion_models/infrastructure/get_response_open_ai.py` | Handles API calls and error mapping |
| Tenant Model | `/backend/src/intric/tenants/tenant.py` | Tenant database model with credentials |

---

**Document Version**: 1.0
**Last Updated**: 2025-01-15
**Target vLLM Version**: OpenAI-compatible API (v1)
