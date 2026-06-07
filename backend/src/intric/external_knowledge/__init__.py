"""Provider-agnostic external knowledge integration.

A "knowledge source" is a collection created in an external knowledge provider
(configured generically by URL + API key). Eneo registers the collection's MCP
endpoint as a space-scoped MCP server, so the rest of the system treats it like
any other MCP-backed knowledge. No provider/service names leak into the code.
"""
