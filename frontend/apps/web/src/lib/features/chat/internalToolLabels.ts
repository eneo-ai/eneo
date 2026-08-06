/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { m } from "$lib/paraglide/messages";

type ToolArgs = Record<string, unknown> | undefined;

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
  {
    label: () => string;
    tools: Record<
      string,
      { running: (args?: ToolArgs) => string; done: (args?: ToolArgs) => string }
    >;
  }
> = {
  knowledge: {
    label: () => m.knowledge(),
    tools: {
      // The search query is folded into the label ("Sökte ”x” i kunskapen")
      // so it reads as a sentence rather than a detached parameter.
      search_knowledge: {
        running: (args) => {
          const query = searchQuery(args);
          return query ? m.tool_search_knowledge_query({ query }) : m.tool_search_knowledge();
        },
        done: (args) => {
          const query = searchQuery(args);
          return query
            ? m.tool_search_knowledge_query_done({ query })
            : m.tool_search_knowledge_done();
        }
      },
      list_knowledge_sources: {
        running: () => m.tool_list_knowledge_sources(),
        done: () => m.tool_list_knowledge_sources_done()
      },
      read_source: {
        running: () => m.tool_read_source(),
        done: () => m.tool_read_source_done()
      }
    }
  },
  files: {
    label: () => m.internal_files_server(),
    tools: {
      read_file: {
        running: () => m.tool_read_file(),
        done: () => m.tool_read_file_done()
      }
    }
  }
};

/** Whether a server name refers to one of Eneo's built-in loopback servers. */
export function isInternalServer(serverName: string): boolean {
  return serverName in INTERNAL_SERVERS;
}

/**
 * Past-tense label for a finished internal tool call ("Sökte i kunskap"), or
 * null for external servers and unknown internal tools.
 */
export function internalToolDoneLabel(
  toolName: string,
  serverName: string,
  args?: ToolArgs
): string | null {
  return INTERNAL_SERVERS[serverName]?.tools[toolName]?.done(args) ?? null;
}

/**
 * Display name for a tool call: internal mapping > server title > raw name.
 * The internal mapping only applies to Eneo's own loopback servers.
 */
export function toolDisplayName(
  toolName: string,
  serverName: string,
  title?: string | null,
  args?: ToolArgs
): string {
  const internal = INTERNAL_SERVERS[serverName];
  if (internal) {
    return internal.tools[toolName]?.running(args) ?? title ?? toolName;
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

/** Longest query shown inline in a tool label before being cut with an ellipsis. */
const MAX_INLINE_QUERY_LENGTH = 60;

/** Query argument of a search_knowledge call, if present and non-empty. */
function searchQuery(args?: ToolArgs): string | null {
  const query = args?.query;
  if (typeof query !== "string") return null;
  const trimmed = query.trim();
  if (trimmed.length === 0) return null;
  return trimmed.length > MAX_INLINE_QUERY_LENGTH
    ? `${trimmed.slice(0, MAX_INLINE_QUERY_LENGTH)}…`
    : trimmed;
}
