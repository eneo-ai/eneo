/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { m } from "$lib/paraglide/messages";

/**
 * Localized display labels for Eneo's own built-in tools (the loopback
 * internal-MCP servers). External MCP servers provide their own titles and
 * are shown as-is; this mapping only overrides names Eneo itself ships, so
 * they follow the UI language instead of the server-side English titles.
 * Keyed by server name so an external server exposing a tool named e.g.
 * `search_knowledge` cannot pass itself off as built-in Eneo knowledge.
 */
const INTERNAL_SERVERS: Record<
  string,
  { label: () => string; tools: Record<string, () => string> }
> = {
  knowledge: {
    label: () => m.knowledge(),
    tools: {
      search_knowledge: () => m.tool_search_knowledge(),
      list_knowledge_sources: () => m.tool_list_knowledge_sources(),
      read_source: () => m.tool_read_source()
    }
  },
  files: {
    label: () => m.internal_files_server(),
    tools: {
      read_file: () => m.tool_read_file()
    }
  }
};

/**
 * Display name for a tool call: internal mapping > server title > raw name.
 * The internal mapping only applies to Eneo's own loopback servers.
 */
export function toolDisplayName(
  toolName: string,
  serverName: string,
  title?: string | null
): string {
  const internal = INTERNAL_SERVERS[serverName];
  if (internal) {
    return internal.tools[toolName]?.() ?? title ?? toolName;
  }
  return title ?? toolName;
}

/** Display name for the server line under a tool call. */
export function serverDisplayName(serverName: string): string {
  return INTERNAL_SERVERS[serverName]?.label() ?? serverName;
}

/** Path of a signed attachment download URL, mirroring the backend's parser. */
const FILE_DOWNLOAD_PATH = /\/api\/v1\/files\/([0-9a-fA-F-]{36})\/download\/?$/;

/**
 * File id referenced by a read_file call on Eneo's internal files server, or
 * null for any other tool call. Lets the UI resolve which attachment a tool
 * call is reading and show its filename.
 */
export function internalReadFileId(
  serverName: string,
  toolName: string,
  args?: Record<string, unknown>
): string | null {
  if (serverName !== "files" || toolName !== "read_file") return null;
  const url = args?.url;
  if (typeof url !== "string") return null;
  try {
    return FILE_DOWNLOAD_PATH.exec(new URL(url).pathname)?.[1] ?? null;
  } catch {
    return null;
  }
}
