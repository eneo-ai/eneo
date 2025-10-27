# Architecture Guide

This guide covers Eneo's technical architecture, design patterns, and system components.

---

## System Overview

Eneo uses a microservices architecture with domain-driven design principles for scalability, maintainability, and democratic AI governance.

### Core Principles

- **Domain-Driven Design** - Business logic organized by domain boundaries
- **Event-Driven Architecture** - Asynchronous processing via Redis pub/sub
- **API-First Design** - OpenAPI specification with auto-generated documentation
- **Multi-Tenancy** - Secure isolation between organizations
- **Real-Time Communication** - WebSockets and Server-Sent Events
- **Security by Design** - Built-in compliance and access control

---

## System Context (C4 Level 1)

The Eneo system serves public sector organizations by providing AI-powered collaborative workspaces. This diagram shows how Eneo interacts with its users and external systems.

```mermaid
%%{init: {'theme': 'base'}}%%
graph LR
    classDef user fill:#bfdbfe,stroke:#1e40af,stroke-width:2px,color:#1e3a8a
    classDef system fill:#d1fae5,stroke:#15803d,stroke-width:2px,color:#14532d
    classDef adapter fill:#fed7aa,stroke:#c2410c,stroke-width:2px,color:#7c2d12
    classDef external fill:#f5d0fe,stroke:#a21caf,stroke-width:2px,color:#701a75

    Users["End Users<br/>(Employees, Analysts)"]
    Admins["System Administrators<br/>(IT, Operations)"]

    Eneo["Eneo Platform<br/>AI Workspaces & Document Processing"]

    LiteLLM["LiteLLM Adapter<br/>Unified AI Interface"]

    AI["AI Providers<br/>(OpenAI, Anthropic, Azure,<br/>vLLM, Berget, Local Models)"]
    IdP["Identity Providers<br/>(Optional: Entra ID,<br/>Auth0, MobilityGuard)"]

    Users -->|Create spaces,<br/>ask questions| Eneo
    Admins -->|Configure tenants,<br/>manage credentials| Eneo

    Eneo -->|Route requests| LiteLLM
    LiteLLM -->|Provider-specific APIs| AI
    Eneo -.->|Authenticate users| IdP

    class Users,Admins user
    class Eneo system
    class LiteLLM adapter
    class AI,IdP external
```

---

## High-Level Architecture (C4 Level 2)

This diagram shows the core deployable containers and their interactions. Note: Traefik reverse proxy shown here is part of the production deployment example (see [DEPLOYMENT.md](./DEPLOYMENT.md)) and can be replaced with other solutions like Nginx, Kubernetes Ingress, etc.

<details>
<summary>View complete system architecture</summary>

```mermaid
%%{init: {'theme': 'base'}}%%
graph TD
    classDef userFacing fill:#bfdbfe,stroke:#1e40af,stroke-width:2px,color:#1e3a8a
    classDef appLogic fill:#d1fae5,stroke:#15803d,stroke-width:2px,color:#14532d
    classDef dataStore fill:#fecaca,stroke:#b91c1c,stroke-width:2px,color:#7f1d1d
    classDef caching fill:#fef08a,stroke:#ca8a04,stroke-width:2px,color:#713f12
    classDef external fill:#f5d0fe,stroke:#a21caf,stroke-width:2px,color:#701a75
    classDef workers fill:#fed7aa,stroke:#c2410c,stroke-width:2px,color:#7c2d12

    subgraph "User Clients"
        WEB[Web Browser]
        API[API Clients]
    end

    subgraph "Application Layer"
        FE[Frontend Container<br/>SvelteKit on Node.js<br/>Port 3000]
        BE[Backend Container<br/>FastAPI on Uvicorn<br/>Port 8000]
        WK[Worker Container<br/>ARQ Background Tasks]
    end

    subgraph "Data Layer"
        DB[(PostgreSQL 16<br/>+ pgvector)]
        REDIS[(Redis<br/>Cache/Queue/PubSub)]
        FS[File Storage<br/>Volume Mounts]
    end

    subgraph "External AI Providers"
        OPENAI[OpenAI]
        ANTHROPIC[Anthropic]
        AZURE[Azure OpenAI]
        LOCAL[Local Models]
    end

    WEB --> FE
    API --> BE

    FE -->|HTTP/SSE/WebSocket| BE

    BE --> DB
    BE --> REDIS
    BE --> FS
    BE --> OPENAI
    BE --> ANTHROPIC
    BE --> AZURE
    BE --> LOCAL

    WK -.->|Dequeue jobs| REDIS
    WK --> DB
    WK --> FS

    class WEB,API userFacing
    class FE userFacing
    class BE appLogic
    class WK workers
    class DB,FS dataStore
    class REDIS caching
    class OPENAI,ANTHROPIC,AZURE,LOCAL external
```

**Key Components:**
- **Frontend**: Serves the web UI and proxies API requests
- **Backend**: FastAPI application with domain services (authentication, spaces, assistants, files, AI integration)
- **Worker**: ARQ processes background tasks (file processing, web crawling, transcription, document embedding)
- **PostgreSQL**: Primary database with pgvector for semantic search
- **Redis**: Caching, job queue, and pub/sub messaging

</details>

---

## Domain-Driven Design Structure

Eneo implements DDD patterns with clear domain boundaries and consistent architectural patterns.

### Domain Organization

```
backend/src/intric/
├── assistants/           # AI Assistant Management Domain
├── spaces/              # Collaborative Workspaces Domain
├── users/               # User Management Domain
├── completion_models/   # AI Model Integration Domain
├── embedding_models/    # Vector Search Domain
├── files/               # Document Processing Domain
├── sessions/            # Conversation Management Domain
├── authentication/     # Security and Access Control Domain
├── groups_legacy/       # User Groups Domain (Legacy)
├── tenants/            # Multi-tenancy Domain
└── workflows/          # Business Process Automation Domain
```

### Domain Pattern Structure

Each domain follows a consistent layered architecture:

<details>
<summary>View domain structure pattern</summary>

```
domain_name/
├── api/                           # Presentation Layer
│   ├── domain_models.py          # Pydantic schemas for API
│   ├── domain_router.py          # FastAPI route definitions
│   └── domain_assembler.py       # Domain-to-API transformation
├── application/                   # Application Layer
│   └── domain_service.py         # Business logic and use cases
├── domain/                        # Domain Layer
│   ├── domain.py                 # Domain entities and value objects
│   └── domain_repo.py            # Repository interfaces
├── infrastructure/               # Infrastructure Layer
│   └── domain_repo_impl.py       # Repository implementations
├── domain_factory.py             # Domain object creation
└── __init__.py
```

**Layer Responsibilities:**
- **API Layer**: HTTP request/response handling, data validation
- **Application Layer**: Business use cases, orchestration
- **Domain Layer**: Core business logic, entities, rules
- **Infrastructure Layer**: Database access, external services

</details>

---

## Frontend Architecture (C4 Level 3)

Deep dive into the SvelteKit frontend container showing components, state management, and data flow. This diagram illustrates how the frontend is organized using Svelte 5's reactive patterns and how it communicates with backend services.

<details>
<summary>View SvelteKit application structure</summary>

```mermaid
%%{init: {'theme': 'base'}}%%
graph LR
    classDef userFacing fill:#bfdbfe,stroke:#1e40af,stroke-width:2px,color:#1e3a8a
    classDef appLogic fill:#d1fae5,stroke:#15803d,stroke-width:2px,color:#14532d

    subgraph "SvelteKit Frontend"
        ROUTES[File-based Routing<br/>src/routes/]
        COMPONENTS[Reusable Components<br/>src/lib/components/]
        STORES[State Management<br/>Svelte Stores]
        SERVICES[API Services<br/>@intric/intric-js]
        I18N[Internationalization<br/>Paraglide-JS]
    end

    subgraph "UI Layer"
        PAGES[Pages/Routes]
        LAYOUTS[Layout Components]
        WIDGETS[UI Widgets]
    end

    subgraph "State Layer"
        AUTH_STORE[Authentication Store]
        SPACE_STORE[Space Store]
        CHAT_STORE[Chat Store]
        THEME_STORE[Theme Store]
    end

    ROUTES --> PAGES
    COMPONENTS --> LAYOUTS
    COMPONENTS --> WIDGETS
    STORES --> AUTH_STORE
    STORES --> SPACE_STORE
    STORES --> CHAT_STORE
    STORES --> THEME_STORE

    SERVICES --> PAGES
    I18N --> PAGES

    class PAGES,LAYOUTS,WIDGETS,ROUTES,COMPONENTS,SERVICES,I18N userFacing
    class STORES,AUTH_STORE,SPACE_STORE,CHAT_STORE,THEME_STORE appLogic
```

</details>

### Key Frontend Technologies

- **Framework**: SvelteKit with TypeScript
- **Package Manager**: bun with workspace support
- **UI Components**: Custom component library (@intric/ui)
- **Styling**: Tailwind CSS v4
- **API Client**: Type-safe client (@intric/intric-js)
- **State Management**: Svelte stores with reactive updates
- **Internationalization**: Paraglide-JS for Swedish/English
- **Build Tool**: Vite for development and production builds

---

## Backend Architecture (C4 Level 3)

Deep dive into the FastAPI backend container showing the layered architecture with HTTP handling, domain services, domain entities, and infrastructure components. This demonstrates how Eneo implements domain-driven design principles with clear separation of concerns across layers.

### FastAPI Application Structure

<details>
<summary>View backend architecture diagram</summary>

```mermaid
%%{init: {'theme': 'base'}}%%
graph TB
    classDef infra fill:#e5e7eb,stroke:#374151,stroke-width:2px,color:#1f2937
    classDef appLogic fill:#d1fae5,stroke:#15803d,stroke-width:2px,color:#14532d
    classDef domain fill:#fed7aa,stroke:#c2410c,stroke-width:2px,color:#7c2d12
    classDef dataStore fill:#fecaca,stroke:#b91c1c,stroke-width:2px,color:#7f1d1d
    classDef caching fill:#fef08a,stroke:#ca8a04,stroke-width:2px,color:#713f12

    subgraph "HTTP Layer"
        ROUTES[FastAPI Routers]
        MIDDLEWARE[Middleware Stack]
        DEPS[Dependency Injection]
    end

    subgraph "Application Layer"
        SERVICES[Domain Services]
        FACTORIES[Domain Factories]
        REPOS[Repository Layer]
    end

    subgraph "Domain Layer"
        ENTITIES[Domain Entities]
        VALUE_OBJECTS[Value Objects]
        DOMAIN_SERVICES[Domain Services]
        EVENTS[Domain Events]
    end

    subgraph "Infrastructure Layer"
        ORM[SQLAlchemy ORM]
        MIGRATIONS[Alembic Migrations]
        CACHE[Redis Cache]
        QUEUE[ARQ Task Queue]
        STORAGE[File Storage]
        AI_CLIENTS[AI Provider Clients]
    end

    ROUTES --> SERVICES
    MIDDLEWARE --> ROUTES
    DEPS --> SERVICES

    SERVICES --> FACTORIES
    SERVICES --> REPOS
    FACTORIES --> ENTITIES
    REPOS --> ORM

    ENTITIES --> VALUE_OBJECTS
    ENTITIES --> DOMAIN_SERVICES
    DOMAIN_SERVICES --> EVENTS

    ORM --> MIGRATIONS
    CACHE --> QUEUE
    STORAGE --> AI_CLIENTS

    class ROUTES,MIDDLEWARE,DEPS infra
    class SERVICES,FACTORIES,REPOS appLogic
    class ENTITIES,VALUE_OBJECTS,DOMAIN_SERVICES,EVENTS domain
    class ORM,MIGRATIONS dataStore
    class CACHE caching
    class QUEUE,STORAGE,AI_CLIENTS infra
```

</details>

### Core Backend Components

**Framework Stack:**
- **FastAPI**: Modern async web framework
- **SQLAlchemy**: ORM with async support
- **Alembic**: Database migration management
- **Pydantic**: Data validation and serialization
- **ARQ**: Async Redis Queue for background tasks

**Architecture Patterns:**
- **Repository Pattern**: Data access abstraction
- **Factory Pattern**: Complex object creation
- **Dependency Injection**: Service composition
- **Event Sourcing**: Domain event handling
- **CQRS**: Command Query Responsibility Segregation

---

## Data Architecture

This section describes how Eneo manages data across PostgreSQL, Redis, and file storage, with particular emphasis on multi-tenancy and vector search capabilities.

### Database Design

The entity relationship diagram shows the core entities and their relationships. The database is organized around tenant isolation, ensuring complete data separation between organizations while maintaining referential integrity.

<details>
<summary>View database schema overview</summary>

```mermaid
%%{init: {'theme': 'base'}}%%
erDiagram
    %% Note: FILES table has a 'transcription' TEXT column for storing transcription results
    %% TRANSCRIPTION_MODELS table exists separately for available AI transcription models

    TENANTS ||--o{ USERS : contains
    TENANTS ||--o{ SPACES : contains
    TENANTS ||--o{ ROLES : defines

    USERS ||--o{ SESSIONS : creates
    USERS }o--o{ USER_GROUPS : belongs_to
    USERS ||--o{ API_KEYS : owns

    SPACES ||--o{ ASSISTANTS : contains
    SPACES ||--o{ INFO_BLOBS : stores
    SPACES }o--o{ USER_GROUPS : accessible_by

    ASSISTANTS ||--o{ SESSIONS : powers
    ASSISTANTS }o--|| COMPLETION_MODELS : uses
    ASSISTANTS }o--o{ PROMPTS : configured_with

    SESSIONS ||--o{ QUESTIONS : contains
    QUESTIONS }o--o{ INFO_BLOBS : references
    QUESTIONS }o--|| FILES : may_include

    INFO_BLOBS ||--o{ INFO_BLOB_CHUNKS : split_into
    INFO_BLOB_CHUNKS }o--|| EMBEDDING_MODELS : embedded_by

    COMPLETION_MODELS }o--o{ USER_GROUPS : available_to
    EMBEDDING_MODELS }o--o{ USER_GROUPS : available_to

    TENANTS {
        uuid id PK
        string name
        string display_name
        jsonb settings
        timestamp created_at
        timestamp updated_at
    }

    USERS {
        uuid id PK
        uuid tenant_id FK
        string email
        string username
        string password_hash
        jsonb settings
        timestamp deleted_at
        timestamp created_at
        timestamp updated_at
    }

    SPACES {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string name
        string description
        jsonb settings
        timestamp created_at
        timestamp updated_at
    }

    ASSISTANTS {
        uuid id PK
        uuid space_id FK
        uuid completion_model_id FK
        string name
        string description
        jsonb configuration
        timestamp created_at
        timestamp updated_at
    }
```

</details>

### Key Data Patterns

**Multi-tenancy:**
- All entities include `tenant_id` for data isolation
- Row-level security ensures tenant separation
- UUID primary keys prevent enumeration attacks

**Soft Deletes:**
- Users support soft deletion with `deleted_at` timestamp
- Maintains referential integrity while hiding deleted records

**Audit Trails:**
- All entities include `created_at` and `updated_at` timestamps
- Database triggers maintain accurate timestamps
- Comprehensive logging for compliance requirements

**Vector Storage:**
- PostgreSQL with pgvector extension for semantic search
- Embeddings stored alongside metadata in `info_blob_chunks`
- Efficient similarity search with indexing strategies

---

## Multi-Tenancy Architecture

Eneo supports enterprise multi-tenancy with complete data isolation, per-tenant identity providers, and encrypted credential management.

### Tenant Isolation

**Database Level:**
- All entities include `tenant_id` for row-level security
- PostgreSQL policies enforce tenant separation
- UUID primary keys prevent enumeration

**Authentication Modes:**

- **Single-Tenant (Default)** - Shared IdP via `OIDC_DISCOVERY_ENDPOINT`
- **Multi-Tenant Federation** - Per-tenant IdPs (Entra ID, MobilityGuard, Auth0, Okta), encrypted with Fernet, enabled via `FEDERATION_PER_TENANT_ENABLED=true`

**Federation Configuration:**
```bash
# Example: Entra ID for a municipality
PUT /api/v1/sysadmin/tenants/{tenant_id}/federation
{
  "provider": "entra_id",
  "discovery_endpoint": "https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration",
  "client_id": "...",
  "client_secret": "...",  # Encrypted at rest
  "allowed_domains": ["municipality.gov"]
}

# Example: MobilityGuard
PUT /api/v1/sysadmin/tenants/{tenant_id}/federation
{
  "provider": "mobilityguard",
  "discovery_endpoint": "https://login.mobilityguard.com/.well-known/openid-configuration",
  "client_id": "...",
  "client_secret": "...",
  "allowed_domains": ["municipality.se"]
}
```

**Credential Management:**

- **Shared Mode** (`TENANT_CREDENTIALS_ENABLED=false`) - All tenants use global API keys
- **Strict Mode** (`TENANT_CREDENTIALS_ENABLED=true`) - Each tenant configures encrypted credentials

Supported providers: OpenAI, Anthropic, Azure, vLLM, Berget, Mistral. All credentials encrypted with Fernet using `ENCRYPTION_KEY`. Additional encrypted data includes crawler HTTP auth and custom integration secrets.

Configure via: `PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}`

**See Also:**
- [Federation Per Tenant](./FEDERATION_PER_TENANT.md) - IdP architecture
- [Multi-Tenant Credentials](./MULTI_TENANT_CREDENTIALS.md) - Detailed credential management
- [Multi-Tenant OIDC Setup](./MULTITENANT_OIDC_SETUP_GUIDE.md) - Provisioning guide

### Observability & Debugging

**OIDC Debug Toggle:**

Enable verbose authentication logging without redeployment for troubleshooting:

```bash
POST /api/v1/sysadmin/observability/oidc-debug/
{
  "enabled": true,
  "duration_minutes": 10,
  "reason": "Investigating login issue #452"
}
```

**Workflow:** Enable toggle → Reproduce issue → Capture `correlationId` from UI → Filter logs: `journalctl | jq 'select(.correlation_id=="abc123")'` → Identify misconfiguration → Disable toggle

**See Also:** [Multi-Tenant OIDC Setup Guide](./MULTITENANT_OIDC_SETUP_GUIDE.md#3-runtime-debugging-correlation-id-based)

---

## Real-Time Communication

Eneo uses Server-Sent Events (SSE) for streaming AI responses and WebSockets for general-purpose real-time updates.

### Communication Patterns

The sequence diagram below illustrates two key flows: (1) synchronous AI chat with streaming responses via SSE, and (2) asynchronous file processing with status updates via WebSocket.

<details>
<summary>View real-time architecture</summary>

```mermaid
%%{init: {'theme': 'base', 'primaryColor': '#bfdbfe', 'secondBkgColor': '#d1fae5', 'textColor': '#1f2937'}}%%
sequenceDiagram
    participant C as Client
    participant F as Frontend
    participant B as Backend
    participant AI as AI Provider
    participant R as Redis
    participant W as Worker

    rect rgb(191, 219, 254)
        Note over C,AI: Chat Streaming (SSE)
    end

    C->>F: Send message
    F->>B: POST /api/v1/assistants/{id}/sessions/<br/>(stream=true)
    B->>AI: Request completion (streaming)
    AI-->>B: Stream response chunks
    B-->>F: SSE stream chunks
    F-->>C: Display message real-time

    rect rgb(254, 215, 170)
        Note over C,W: Knowledge Base File Processing (ARQ + WebSocket)
    end

    C->>F: Upload file to collection
    F->>B: POST /api/v1/groups/{id}/info-blobs/upload/
    B->>B: Save file to /tmp disk
    B->>R: Enqueue job (job_manager)
    B-->>F: 202 Accepted (JobPublic with job_id)
    F-->>C: Processing queued...

    W->>R: Dequeue transcription_task or<br/>upload_info_blob_task
    activate W
    W->>W: Transcribe/Parse/Chunk/Embed file
    W->>R: Publish status to Pub/Sub channel
    deactivate W
    R-->>B: Notify via Pub/Sub listener
    B-->>F: WebSocket push (job status update)
    F-->>C: UI shows progress

    W->>R: Publish "complete" to Pub/Sub
    R-->>B: Notify completion
    B-->>F: WebSocket push (final status)
    F-->>C: Processing complete
```

</details>

### Real-Time Technologies

**Server-Sent Events (SSE):**
- Real-time AI response streaming
- Unidirectional server-to-client communication
- Automatic reconnection and error handling
- Browser-native support with EventSource API

**WebSockets:**
- Bidirectional real-time communication
- Background task status updates
- File upload progress tracking
- System-wide notifications

**Redis Pub/Sub:**
- Message broker for real-time events
- Scalable across multiple backend instances
- Event distribution to connected clients
- Persistent connection management

---

## AI Integration

### Multi-Provider Architecture

Eneo supports multiple AI providers through a unified interface, allowing organizations to choose providers based on their needs, compliance requirements, and budget.

**Supported Providers:**
- **OpenAI**: GPT models for general-purpose AI
- **Anthropic**: Claude models for advanced reasoning
- **Azure OpenAI**: Enterprise-grade OpenAI models
- **Local Models**: Self-hosted models for data sovereignty

**Key Features:**
- **Provider Switching**: Change AI providers without code changes
- **Cost Optimization**: Automatic model selection based on cost/performance
- **Fallback Support**: Automatic failover if primary provider is unavailable
- **Usage Tracking**: Monitor costs and performance across providers

---

## Background Processing

### ARQ Task System

Eneo uses ARQ (Async Redis Queue) for handling time-intensive operations that shouldn't block user interactions.

**Common Background Tasks:**
- **File Processing**: Document parsing, image analysis, audio transcription
- **AI Operations**: Embedding generation, batch completions
- **Web Crawling**: Website content extraction and indexing
- **Maintenance**: Database optimization, cache management

**Benefits:**
- **Non-blocking**: Users get immediate responses while processing happens in background
- **Scalable**: Add more worker containers as workload increases
- **Reliable**: Tasks are persisted in Redis and retried on failure
- **Prioritized**: Critical tasks processed before routine maintenance

---

## Security

### Security by Design

Eneo implements security at every layer to protect sensitive public sector data and ensure compliance with European regulations.

**Authentication & Access Control:**
- **JWT Authentication**: Secure token-based sessions
- **Role-Based Access**: Granular permissions by user role
- **Multi-Tenancy**: Complete data isolation between organizations
- **API Keys**: Secure service-to-service authentication

**Data Protection:**
- **Encryption**: AES-256 for data at rest, TLS 1.3 in transit
- **Tenant Data Encryption**: Fernet encryption for tenant credentials and federation configs
- **Password Security**: Bcrypt hashing with secure salts
- **Audit Trails**: All actions logged for compliance
- **Data Retention**: Automatic deletion per policy

**Multi-Tenant Security:**
- Database isolation with row-level security
- Encrypted credentials (Fernet) for LLM keys and IdP secrets
- Per-tenant federation support
- Masked credential responses

**Compliance Ready:**
- **GDPR**: Built-in data subject rights and privacy controls
- **EU AI Act**: Transparency and accountability features
- **Public Sector**: Designed for government security requirements

**See Also:** [Multi-Tenancy Architecture](#multi-tenancy-architecture) for detailed security implementation

---

## Monitoring and Observability

### Built-in Monitoring

Eneo includes comprehensive monitoring capabilities for production deployments.

**System Health:**
- Container resource usage and performance
- Database query performance and connection health
- Background task queue status and processing times
- API response times and error rates

**Business Intelligence:**
- User engagement and feature adoption
- AI model usage patterns and costs
- Document processing statistics
- Space collaboration metrics

**Security Monitoring:**
- Authentication failures and suspicious login attempts
- API rate limiting and abuse detection
- Data access patterns and compliance audits
- System resource anomalies

---

## Deployment Architecture

Eneo is designed to be deployed across multiple environments and orchestration platforms, from local Docker Compose development to Kubernetes production deployments.

### Container Architecture

This diagram shows how Eneo's components are containerized and deployed. Current deployment uses Docker Compose or Podman. Kubernetes support is planned via Helm charts.

<details>
<summary>View container deployment architecture</summary>

```mermaid
%%{init: {'theme': 'base'}}%%
graph TD
    classDef userFacing fill:#bfdbfe,stroke:#1e40af,stroke-width:2px,color:#1e3a8a
    classDef appLogic fill:#d1fae5,stroke:#15803d,stroke-width:2px,color:#14532d
    classDef dataStore fill:#fecaca,stroke:#b91c1c,stroke-width:2px,color:#7f1d1d
    classDef caching fill:#fef08a,stroke:#ca8a04,stroke-width:2px,color:#713f12
    classDef infra fill:#e5e7eb,stroke:#374151,stroke-width:2px,color:#1f2937
    classDef workers fill:#fed7aa,stroke:#c2410c,stroke-width:2px,color:#7c2d12

    EXT[External Traffic<br/>HTTPS]

    subgraph "Gateway Layer (Optional)"
        TRAEFIK[Traefik Container<br/>Reverse Proxy & SSL]
    end

    subgraph "Application Containers"
        FE[Frontend<br/>SvelteKit Server<br/>Port 3000]
        BE[Backend<br/>FastAPI Server<br/>Port 8000]
        WK[Worker<br/>ARQ Tasks]
        INIT[DB Init<br/>Migrations]
    end

    subgraph "Data Containers"
        DB[(PostgreSQL 16<br/>pgvector)]
        REDIS[(Redis 7<br/>Alpine)]
    end

    subgraph "Persistent Volumes"
        DB_VOL[postgres_data]
        REDIS_VOL[redis_data]
        BACKEND_VOL[backend_data]
        CERT_VOL[letsencrypt]
    end

    EXT --> TRAEFIK
    TRAEFIK --> FE
    TRAEFIK --> BE

    FE --> BE
    BE --> DB
    BE --> REDIS

    WK --> REDIS
    WK --> DB

    INIT --> DB

    DB --> DB_VOL
    REDIS --> REDIS_VOL
    BE --> BACKEND_VOL
    TRAEFIK --> CERT_VOL

    class EXT infra
    class TRAEFIK infra
    class FE userFacing
    class BE appLogic
    class WK workers
    class INIT infra
    class DB dataStore
    class REDIS caching
    class DB_VOL,REDIS_VOL,BACKEND_VOL,CERT_VOL dataStore
```

**Deployment Methods:**
- **Docker Compose** (Primary): Orchestrates all containers with networking and volumes
- **Podman**: Docker-compatible alternative, common in RHEL/enterprise environments
- **Kubernetes** (Planned): Helm charts for production-grade orchestration

**Container Images:**
- Frontend: `ghcr.io/eneo-ai/eneo-frontend:latest`
- Backend/Worker: `ghcr.io/eneo-ai/eneo-backend:latest`
- PostgreSQL: `pgvector/pgvector:pg16`
- Redis: `redis:7-alpine`

</details>

### Deployment Strategies

**Development:**
- Docker Compose for local development
- DevContainer for consistent development environment
- Hot reloading for rapid iteration
- Simplified networking and storage

**Production:**
- Multi-stage Docker builds for optimization
- Traefik for SSL termination and load balancing
- Persistent volumes for data storage
- Health checks and restart policies

**Enterprise:**
- Podman for RHEL/enterprise environments
- SystemD integration for service management
- Advanced monitoring and logging

---

## Scalability Considerations

### Horizontal Scaling

**Stateless Services:**
- Frontend and backend services designed as stateless
- Load balancing across multiple instances
- Session data stored in Redis for sharing
- Database connection pooling

**Background Processing:**
- ARQ workers can be scaled independently
- Queue-based task distribution
- Priority-based task processing
- Worker specialization by task type

**Database Scaling:**
- Read replicas for query scaling
- Connection pooling and optimization
- Vector index optimization for pgvector
- Partitioning strategies for large datasets

### Performance Optimization

**Caching Strategy:**
- Redis for session and application caching
- HTTP caching with appropriate headers
- Database query result caching
- Static asset caching via CDN

**AI Provider Optimization:**
- Request batching and queuing
- Response caching for similar queries
- Provider failover and retry logic
- Cost optimization through model selection

---

## Architecture Decision Records

### Key Architectural Decisions

**1. Domain-Driven Design Adoption**
- **Decision**: Organize code by business domains rather than technical layers
- **Rationale**: Better maintainability and team ownership
- **Trade-offs**: Increased complexity for simple features

**2. Multi-Provider AI Integration**
- **Decision**: Abstract AI providers behind unified interface
- **Rationale**: Vendor independence and flexibility
- **Trade-offs**: Additional complexity in provider-specific optimizations

**3. Real-Time Communication Strategy**
- **Decision**: Use SSE for streaming, WebSockets for bidirectional communication
- **Rationale**: Browser compatibility and simplicity
- **Trade-offs**: Separate connection management required

**4. Container-First Deployment**
- **Decision**: Docker/Podman as primary deployment method
- **Rationale**: Consistency across environments and simplified operations
- **Trade-offs**: Container orchestration complexity

---

This architecture supports Eneo's mission of democratic AI by providing a scalable, maintainable, and transparent platform that can grow with the needs of public sector organizations while maintaining the highest standards of security and compliance.
