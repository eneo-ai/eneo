FILES_SERVER_NAME = "files"
KNOWLEDGE_SERVER_NAME = "knowledge"

# Internal tools are read-only core capabilities. User approval controls apply
# to external MCP servers only; these server names are always auto-approved.
INTERNAL_MCP_SERVER_NAMES = frozenset({FILES_SERVER_NAME, KNOWLEDGE_SERVER_NAME})
