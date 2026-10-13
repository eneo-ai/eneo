FILES_SERVER_NAME = "files"
KNOWLEDGE_SERVER_NAME = "knowledge"
# Built-in image generation provider; mounted like the others but attached
# through an admin-registered mcp_servers row rather than ephemerally.
IMAGE_GENERATION_SERVER_NAME = "image_generation"
# Tool-result resource ``_meta`` key naming the citation key (``"D3"``) the
# result's text uses for that resource; the completion layer rewrites the
# bracketed key to the resource's inline reference tag.
CITE_KEY_META = "eneo.cite_key"
