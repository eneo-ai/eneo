"use client";

import { useQuery } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";

/** Re-mint this long before the token actually expires. */
const EXPIRY_MARGIN_MS = 60 * 1000;
const CONTENT_ORIGIN_MISSING_STATUS = 424;

/** Where an approved view is loaded from, and the HTML the sandbox is handed. */
export type ViewLink = { url: string; html: string };

/** Why a view link could not be minted. */
export type ViewLinkError = {
  /** The backend refuses every view until an administrator sets the content origin. */
  contentOriginMissing: boolean;
};

/**
 * The signed link of an approved MCP app view, minted once per view and
 * re-minted when it nears its expiry; a refusal stays until the page reloads.
 */
export function useViewLink(viewId: string): {
  link: ViewLink | null;
  error: ViewLinkError | null;
} {
  const query = useQuery({
    queryKey: ["mcp-apps", "view-link", viewId],
    queryFn: () =>
      unwrap(
        browserApi.POST("/api/v1/mcp-apps/views/{view_id}/token/", {
          params: { path: { view_id: viewId } }
        })
      ),
    staleTime: (query) =>
      query.state.data
        ? Math.max(0, query.state.data.expires_at * 1000 - Date.now() - EXPIRY_MARGIN_MS)
        : 0,
    retry: false
  });
  if (query.data) return { link: { url: query.data.url, html: query.data.html }, error: null };
  if (query.error) {
    const status = (query.error as { status?: unknown }).status;
    return {
      link: null,
      error: { contentOriginMissing: status === CONTENT_ORIGIN_MISSING_STATUS }
    };
  }
  return { link: null, error: null };
}
