/**
 * The tabs of Verktyg and their addresses. A plain module, so the route
 * (a server component) can read the tab from the address, and the client
 * pages can link to a tab.
 */
export type ToolsTab = "functions" | "mcp-servers";

/** The tab a `?tab=` value names; anything else opens the functions. */
export function toolsTabOf(value: string | undefined): ToolsTab {
  return value === "mcp-servers" ? "mcp-servers" : "functions";
}

export const TOOLS_TAB_HREF: Record<ToolsTab, string> = {
  functions: "/admin/tools",
  "mcp-servers": "/admin/tools?tab=mcp-servers"
};
