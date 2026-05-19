TITLE = "Eneo"

SUMMARY = "General AI framework"

TAGS_METADATA = [
    {
        "name": "users",
        "description": "User operations. **Login** logic is here.",
    },
    {
        "name": "user-groups",
        "description": "User groups operations. Use this to manage user groups.",
    },
    {
        "name": "info-blobs",
        "description": (
            "Document operations. **Info-blobs** are blobs of binary information,"
            " not restricted to text, although current support is only text."
        ),
    },
    {
        "name": "groups",
        "description": (
            "Group operations. Use this to organize your info-blobs. **Uploading**"
            " info-blobs is here."
        ),
    },
    {
        "name": "assistants",
        "description": (
            "Assistant operations. Create assistants with the desired configuration and"
            " ask questions to them."
        ),
    },
    {
        "name": "services",
        "description": (
            "Services operations. Documentation for these endpoints are coming soon."
        ),
        "externalDocs": {
            "description": "Services documentation (coming soon)",
            "url": "https://www.eneo.ai/",
        },
    },
    {
        "name": "flows",
        "description": (
            "Flow authoring and runtime operations. Use these endpoints to create draft "
            "flows, manage flow-owned assistants, attach DOCX templates, inspect run "
            "contracts, upload runtime input files, start runs, fetch run outputs, and "
            "drive human-review checkpoints from webapps or service-owned API-key "
            "integrations when the key has Flow write access and owns the run. "
            "For service-key webapps, start with `GET /flows/?space_id=...` or "
            "`GET /flows/{id}/published/`, then follow the returned runtime paths and "
            "`GET /flows/{id}/run-contract/`; `steps_requiring_review` tells clients "
            "whether the published version can pause for human review. Draft authoring "
            "endpoints require a user principal."
        ),
    },
    {
        "name": "ai-builder",
        "description": (
            "AI Builder workflow for flow creation and editing. Recommended consumer "
            "sequence: create or resume a session, send one or more messages, inspect "
            "the proposed plan, approve it, then apply it. All AI Builder endpoints "
            "remain nested under `/flows` because the builder is a flow-drafting subsystem."
        ),
    },
    {
        "name": "flow-packages",
        "description": (
            "Flow package export, validation, and import-planning operations for "
            "portable `.eneo-flowpkg` bundles. Export a draft Flow into a typed "
            "package, validate a package before choosing a target space, then create "
            "a space-scoped import plan to inspect required model, knowledge, MCP, "
            "and template mappings before any imported draft flow is created."
        ),
    },
    {
        "name": "jobs",
        "description": "Job operations. Use this to keep track of running and completed jobs.",
    },
    {
        "name": "logging",
        "description": (
            "Logging operations. Use these endpoints to get exactly what was sent to"
            " the AI-model for each question."
        ),
    },
    {
        "name": "analysis",
        "description": (
            "Analysis operations. Use these endpoints to see how your assistants are"
            " used, as well as to ask questions about the questions asked to an"
            " assistant."
        ),
    },
    {
        "name": "widgets",
        "description": "Widget operations. Use this to save widget settings and run widgets.",
    },
    {
        "name": "allowed-origins",
        "description": (
            "Allowed Origins operations. Use this to specify the allowed origins from"
            " where the widgets will be hosted"
        ),
    },
    {
        "name": "crawls",
        "description": "Crawl operations. Use these endpoint to set up and run crawls.",
    },
    {
        "name": "crawl-runs",
        "description": "Crawl run operations. Use these endpoint to keep track of crawl runs.",
    },
    {
        "name": "roles",
        "description": "User roles. Use this to manage user permissions.",
    },
    {
        "name": "admin",
        "description": "Tenant Admin operations. Manage users, settings, and resources within your specific tenant/organization. Requires admin account API key for your tenant. For system-wide administration across all tenants, see Sysadmin endpoints.",
    },
    {
        "name": "settings",
        "description": (
            "Settings operations. Currently only houses chatbot widget settings."
        ),
    },
    {
        "name": "sysadmin",
        "description": (
            "System Administration operations. Manage the entire Eneo installation across all tenants using the ENEO_SUPER_API_KEY environment variable. Create/manage tenants, system-wide settings, and cross-tenant operations. For single tenant management (users, settings within your organization), see Tenant Admin endpoints."
        ),
    },
    {
        "name": "modules",
        "description": (
            "Module operations. These endpoints are used to handle module access for"
            " tenants. Requires elevated privileges."
        ),
    },
]
