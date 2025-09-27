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
            "url": "https://www.intric.ai/documentation/services",
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
        "name": "websites",
        "description": "Website management operations. Configure websites for crawling, set authentication, update intervals, and manage crawl settings.",
    },
    {
        "name": "crawls",
        "description": "Website crawl operations. Start manual crawls, monitor progress, and configure crawl behavior including file downloads and authentication.",
    },
    {
        "name": "crawl-runs",
        "description": "Crawl execution tracking. Monitor crawl run status, view performance metrics, and access crawl history with detailed timing and error information.",
    },
    {
        "name": "roles",
        "description": "User roles. Use this to manage user permissions.",
    },
    {
        "name": "admin",
        "description": "Admin operations. Use this to manage your tenant.",
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
            "Sysadmin operations. Use the super api key in order to access these"
            " operations."
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
