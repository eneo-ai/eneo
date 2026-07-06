/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { m } from "$lib/paraglide/messages";

/**
 * Localized display labels for Eneo's own built-in tools (the loopback
 * knowledge-MCP server). External MCP servers provide their own titles and
 * are shown as-is; this mapping only overrides names Eneo itself ships, so
 * they follow the UI language instead of the server-side English titles.
 */
const INTERNAL_TOOL_LABELS: Record<string, () => string> = {
  search_knowledge: () => m.tool_search_knowledge(),
  list_knowledge_sources: () => m.tool_list_knowledge_sources(),
  read_source: () => m.tool_read_source()
};

const INTERNAL_SERVER_LABELS: Record<string, () => string> = {
  knowledge: () => m.knowledge()
};

/** Display name for a tool call: internal mapping > server title > raw name. */
export function toolDisplayName(toolName: string, title?: string | null): string {
  return INTERNAL_TOOL_LABELS[toolName]?.() ?? title ?? toolName;
}

/** Display name for the server line under a tool call. */
export function serverDisplayName(serverName: string): string {
  return INTERNAL_SERVER_LABELS[serverName]?.() ?? serverName;
}
