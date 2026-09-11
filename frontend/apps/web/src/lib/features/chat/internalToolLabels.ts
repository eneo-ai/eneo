/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { m } from "$lib/paraglide/messages";
import { getCapability, type CapabilityPurpose } from "$lib/features/mcp/capabilities";

type ToolArgs = Record<string, unknown> | undefined;

/** The parts of a tool call the display rules need. */
type ToolCallLike = { server_name: string; purpose?: string | null };

type CatalogLabels = { title: () => string; description: () => string };

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
    /**
     * Admin-facing title and description per tool, for servers that admins
     * see as catalog rows (built-in providers). Other internal servers are
     * never listed in admin surfaces and carry none.
     */
    catalog?: Record<string, CatalogLabels>;
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
      },
      // No argument folded into the label, unlike search_knowledge: source_id
      // is an opaque UUID and must not surface in the UI.
      describe_source: {
        running: () => m.tool_describe_source(),
        done: () => m.tool_describe_source_done()
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
  },
  // The built-in image generation provider is an admin-named server row over
  // Eneo's loopback server; the backend reports its tool calls under the
  // loopback server's name so the tool follows the UI language too. An
  // external image provider keeps its own name and titles.
  image_generation: {
    label: () => m.image_generation(),
    tools: {
      // One tool covers both: a call carrying reference images is an edit or
      // variation of those images, which reads differently to the user.
      generate_image: {
        running: (args) =>
          hasReferenceImages(args) ? m.tool_edit_image() : m.tool_generate_image(),
        done: (args) =>
          hasReferenceImages(args) ? m.tool_edit_image_done() : m.tool_generate_image_done()
      }
    },
    catalog: {
      generate_image: {
        title: () => m.tool_generate_image_title(),
        description: () => m.tool_generate_image_description()
      }
    }
  }
};

/**
 * Localized admin-facing title and description of a tool on one of Eneo's
 * built-in providers, or null for external servers and unknown tools. A
 * built-in provider is an admin-named server row over the loopback server
 * of its purpose; admin surfaces show synced protocol strings for external
 * servers, while Eneo's own tools follow the UI language.
 */
export function builtinToolCatalogLabels(
  server: { purpose?: string | null; http_auth_type?: string | null },
  toolName: string
): { title: string; description: string } | null {
  if (server.http_auth_type !== "internal" || !server.purpose) return null;
  const labels = INTERNAL_SERVERS[server.purpose]?.catalog?.[toolName];
  return labels ? { title: labels.title(), description: labels.description() } : null;
}

/**
 * Labels for capability calls, keyed by purpose rather than tool name: a
 * capability (web search, image generation) is one function from the user's
 * point of view whichever provider serves it, and external providers name
 * their tools freely. The backend stamps `purpose` on a call served by a
 * capability provider, external or built-in.
 */
const CAPABILITY_STEPS: Record<
  CapabilityPurpose,
  { running: (args?: ToolArgs) => string; done: (args?: ToolArgs) => string }
> = {
  web_search: {
    running: (args) => {
      const query = searchQuery(args);
      return query ? m.tool_web_search_query({ query }) : m.tool_web_search();
    },
    done: (args) => {
      const query = searchQuery(args);
      return query ? m.tool_web_search_query_done({ query }) : m.tool_web_search_done();
    }
  },
  image_generation: INTERNAL_SERVERS.image_generation.tools.generate_image
};

function capabilityPurpose(purpose: string | null | undefined): CapabilityPurpose | null {
  return purpose && purpose in CAPABILITY_STEPS ? (purpose as CapabilityPurpose) : null;
}

/**
 * Skill activations arrive as steps on this pseudo-server: the tool name is
 * the activation key and the title is the Skill's display name. The chat
 * renders them with their own pill (SkillActivationStep); these helpers only
 * cover the labels shared with other built-in steps.
 */
export const SKILLS_SERVER = "skills";

/** Whether a server name refers to one of Eneo's built-in loopback servers. */
export function isInternalServer(serverName: string): boolean {
  return serverName === SKILLS_SERVER || serverName in INTERNAL_SERVERS;
}

/**
 * Whether a tool call renders as a built-in step (slim line, localized
 * labels) rather than as an external tool card: capability calls whichever
 * provider served them, and calls on Eneo's own loopback servers. Rows
 * persisted before `purpose` existed fall back to the server name alone.
 */
export function isBuiltinToolCall(call: ToolCallLike): boolean {
  return capabilityPurpose(call.purpose) !== null || isInternalServer(call.server_name);
}

/**
 * Past-tense label for a finished built-in tool call ("Sökte i kunskap",
 * "Sökte på webben"), or null for external tools and unknown internal tools.
 */
export function internalToolDoneLabel(
  toolName: string,
  serverName: string,
  args?: ToolArgs,
  purpose?: string | null
): string | null {
  const internal = INTERNAL_SERVERS[serverName]?.tools[toolName]?.done(args);
  if (internal) return internal;
  const capability = capabilityPurpose(purpose);
  return capability ? CAPABILITY_STEPS[capability].done(args) : null;
}

/**
 * Display name for a tool call: internal mapping > capability label > server
 * title > raw name. The internal mapping only applies to Eneo's own loopback
 * servers; the capability label to any provider of that capability.
 */
export function toolDisplayName(
  toolName: string,
  serverName: string,
  title?: string | null,
  args?: ToolArgs,
  purpose?: string | null
): string {
  if (serverName === SKILLS_SERVER) {
    return m.tool_activate_skill({ name: title ?? toolName });
  }
  const internal = INTERNAL_SERVERS[serverName]?.tools[toolName]?.running(args);
  if (internal) return internal;
  const capability = capabilityPurpose(purpose);
  if (capability) return CAPABILITY_STEPS[capability].running(args);
  return title ?? toolName;
}

/**
 * Display name for the server line under a tool call: Eneo's own servers and
 * capabilities by their localized name, external general servers by name.
 */
export function serverDisplayName(serverName: string, purpose?: string | null): string {
  if (serverName === SKILLS_SERVER) return m.skills();
  const internal = INTERNAL_SERVERS[serverName]?.label();
  if (internal) return internal;
  const capability = capabilityPurpose(purpose);
  return capability ? (getCapability(capability)?.label() ?? serverName) : serverName;
}

/**
 * The provider's own name for a capability call served by an external
 * provider ("GDM Safe Search"), shown as the step's detail so the source
 * stays visible; null for Eneo's own servers and general tools.
 */
export function capabilityProviderDetail(call: ToolCallLike): string | null {
  if (capabilityPurpose(call.purpose) === null || isInternalServer(call.server_name)) {
    return null;
  }
  return call.server_name;
}

/** Path of a signed file reference URL, mirroring the backend's parser. */
const FILE_DOWNLOAD_PATH = /\/api\/v1\/files\/([0-9a-fA-F-]{36})\/original\/download\/?$/;

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

/** Whether a generate_image call edits reference images rather than starting from text. */
function hasReferenceImages(args?: ToolArgs): boolean {
  const references = args?.reference_images;
  return Array.isArray(references) && references.length > 0;
}

/** Longest query shown inline in a tool label before being cut with an ellipsis. */
const MAX_INLINE_QUERY_LENGTH = 60;

/** Query argument of a search call (`query`, or `q` as some providers name it). */
function searchQuery(args?: ToolArgs): string | null {
  const query = args?.query ?? args?.q;
  if (typeof query !== "string") return null;
  const trimmed = query.trim();
  if (trimmed.length === 0) return null;
  return trimmed.length > MAX_INLINE_QUERY_LENGTH
    ? `${trimmed.slice(0, MAX_INLINE_QUERY_LENGTH)}…`
    : trimmed;
}
