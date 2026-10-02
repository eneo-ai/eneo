from pydantic import BaseModel


class McpAppViewTokenResponse(BaseModel):
    """Approved HTML and a signed URL for its trusted sandbox proxy."""

    url: str
    expires_at: int
    html: str
