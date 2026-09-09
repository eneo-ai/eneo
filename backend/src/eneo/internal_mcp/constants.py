FILES_SERVER_NAME = "files"
KNOWLEDGE_SERVER_NAME = "knowledge"
# Insights analysis tools over a target assistant's or group chat's
# conversations; attached only by the insights chat, never by assistants.
INSIGHTS_SERVER_NAME = "insights"
# Built-in image generation provider; mounted like the others but attached
# through an admin-registered mcp_servers row rather than ephemerally.
IMAGE_GENERATION_SERVER_NAME = "image_generation"

# Internal tools are read-only core capabilities. User approval controls apply
# to external MCP servers only; these server names are always auto-approved.
INTERNAL_MCP_SERVER_NAMES = frozenset(
    {FILES_SERVER_NAME, KNOWLEDGE_SERVER_NAME, INSIGHTS_SERVER_NAME}
)
