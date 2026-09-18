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
        "description": (
            "Embeddable widgets. Publish an assistant as a chat widget on an"
            " external website and manage its configuration, activation and"
            " tenant policy."
        ),
    },
    {
        "name": "allowed-origins",
        "description": (
            "Allowed Origins operations. Lists the origins that may make"
            " cross-origin requests to this API, such as additional frontend"
            " domains."
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
            "Settings operations. Read the current user's settings and the models"
            " and formats available to them."
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
