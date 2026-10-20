"""Redis keys the SharePoint sync tasks and the webhook service agree on.

A sync task holds ``sync_lock_key`` for the knowledge it syncs. Anyone who
wants a sync while that lease is held leaves ``sync_pending_key``; the lease
holder runs one more delta pass before releasing. The marker is deleted when
drained; the TTL only guards against leaks and must outlive any sync, since
Graph does not notify again for a change it already reported.
"""

SHAREPOINT_SYNC_PENDING_TTL_SECONDS = 24 * 3600


def sync_lock_key(knowledge_id: str) -> str:
    return f"sharepoint_sync_lock:{knowledge_id}"


def sync_pending_key(knowledge_id: str) -> str:
    return f"sharepoint_sync_pending:{knowledge_id}"
