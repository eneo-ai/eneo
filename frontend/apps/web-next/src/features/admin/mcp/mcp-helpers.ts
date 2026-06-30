import type { McpServer, McpServerTool } from "./mcp";

/** Host portion of a server URL for display ("api.github.com"), null if unparseable. */
export function hostFromUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).host || null;
  } catch {
    const match = url.match(/^[a-z][a-z0-9+.-]*:\/\/([^/?#]+)/i);
    return match?.[1] ?? null;
  }
}

/** Up to two uppercase initials for an avatar fallback. */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0]!.slice(0, 2).toUpperCase();
  return (words[0]![0]! + words[words.length - 1]![0]!).toUpperCase();
}

/** Tools awaiting admin review (new / changed / removed-from-remote). */
export function pendingTools(tools: readonly McpServerTool[]): McpServerTool[] {
  return tools.filter((tool) => tool.requires_approval);
}

/** Tools active for the tenant (enabled and not pending review). */
export function activeToolCount(tools: readonly McpServerTool[]): number {
  return tools.filter((tool) => !tool.requires_approval && tool.is_enabled_by_default).length;
}

/**
 * A server is quarantined when security classifications are enforced org-wide
 * but this server has none — it must be classified before it can be enabled.
 */
export function isQuarantined(server: McpServer, securityEnabled: boolean): boolean {
  return securityEnabled && !server.security_classification;
}

export type ToolRisk = "read" | "write";

// Verb tokens that imply a tool can change state. The signal is a heuristic over
// the tool name (MCP tools are conventionally verb-first), not an authoritative
// capability flag — surfaced as "best guess" until the backend provides one.
const WRITE_TOKENS = new Set([
  "create",
  "update",
  "delete",
  "write",
  "send",
  "post",
  "put",
  "patch",
  "remove",
  "set",
  "add",
  "insert",
  "upsert",
  "edit",
  "modify",
  "move",
  "rename",
  "archive",
  "publish",
  "deploy",
  "run",
  "execute",
  "exec",
  "trigger",
  "cancel",
  "approve",
  "reject",
  "merge",
  "push",
  "upload",
  "revoke",
  "grant",
  "reset",
  "drop",
  "destroy",
  "disable",
  "enable",
  "close",
  "assign",
  "unassign",
  "submit",
  "schedule",
  "provision",
  "restart",
  "start",
  "stop",
  "kill",
  "apply",
  "clear",
  "purge"
]);

function tokenize(name: string): string[] {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[^a-zA-Z0-9]+/)
    .filter(Boolean)
    .map((token) => token.toLowerCase());
}

/** Best-effort read/write classification from a tool's name. */
export function toolRisk(tool: { name: string }): ToolRisk {
  return tokenize(tool.name).some((token) => WRITE_TOKENS.has(token)) ? "write" : "read";
}

export type ToolParam = {
  name: string;
  type: string;
  required: boolean;
  description: string | null;
};

function schemaType(def: Record<string, unknown>): string {
  const type = def.type;
  if (typeof type === "string") {
    if (type === "array") {
      const items = def.items;
      const itemType =
        items && typeof items === "object" ? (items as Record<string, unknown>).type : undefined;
      return typeof itemType === "string" ? `${itemType}[]` : "array";
    }
    return type;
  }
  if (Array.isArray(type)) {
    const names = type.filter((entry): entry is string => typeof entry === "string");
    return names.length > 0 ? names.join(" | ") : "any";
  }
  if (Array.isArray((def as { enum?: unknown }).enum)) return "enum";
  return "any";
}

/**
 * Flatten a tool's JSON Schema into a human-readable parameter list
 * (name · type · required · description) for non-developer admins.
 */
export function readableParams(schema: Record<string, unknown> | null | undefined): ToolParam[] {
  if (!schema || typeof schema !== "object") return [];
  const properties = (schema as { properties?: unknown }).properties;
  if (!properties || typeof properties !== "object") return [];
  const requiredRaw = (schema as { required?: unknown }).required;
  const required = Array.isArray(requiredRaw)
    ? requiredRaw.filter((entry): entry is string => typeof entry === "string")
    : [];

  return Object.entries(properties as Record<string, unknown>).map(([name, value]) => {
    const def = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
    return {
      name,
      type: schemaType(def),
      required: required.includes(name),
      description: typeof def.description === "string" ? def.description : null
    };
  });
}
