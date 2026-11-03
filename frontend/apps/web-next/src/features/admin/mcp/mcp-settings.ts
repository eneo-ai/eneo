import type { McpAuthType, McpServer, McpServerUpdatePayload } from "./mcp";

export type CredentialDraft = { auth: McpAuthType; token: string; headerName: string };

/** An omitted config preserves saved credentials, including an API header name. */
export function credentialPayload(draft: CredentialDraft) {
  if (!draft.token.trim() || draft.auth === "none") return undefined;
  return draft.auth === "api_key_header" && draft.headerName.trim()
    ? { header_name: draft.headerName.trim(), token: draft.token }
    : { token: draft.token };
}

export const CATALOG_LIMITS = [
  {
    field: "toolCatalogMaxCount",
    api: "tool_catalog_max_count",
    label: "mcp_catalog_max_count",
    hint: "mcp_catalog_max_count_hint",
    max: 4096,
    default: 256,
    unit: 1
  },
  {
    field: "toolCatalogMaxMiB",
    api: "tool_catalog_max_bytes",
    label: "mcp_catalog_max_mib",
    hint: "mcp_catalog_max_mib_hint",
    max: 64,
    default: 16,
    unit: 1048576
  },
  {
    field: "toolDefinitionMaxKiB",
    api: "tool_definition_max_bytes",
    label: "mcp_tool_definition_max_kib",
    hint: "mcp_tool_definition_max_kib_hint",
    max: 1024,
    default: 64,
    unit: 1024
  }
] as const;
export type CatalogField = (typeof CATALOG_LIMITS)[number]["field"];
export type CatalogDraft = Record<CatalogField, number>;

export function catalogDraft(server?: McpServer | null): CatalogDraft {
  const [count, catalog, definition] = CATALOG_LIMITS;
  return {
    toolCatalogMaxCount: server?.[count.api] ?? count.default,
    toolCatalogMaxMiB: (server?.[catalog.api] ?? catalog.default * catalog.unit) / catalog.unit,
    toolDefinitionMaxKiB:
      (server?.[definition.api] ?? definition.default * definition.unit) / definition.unit
  };
}

export function catalogProblems(draft: CatalogDraft) {
  return CATALOG_LIMITS.filter(
    ({ field, max }) => !Number.isInteger(draft[field]) || draft[field] < 1 || draft[field] > max
  ).map(({ field, max }) => ({ field, kind: "whole-number" as const, min: 1, max }));
}

export function catalogPayload(draft: CatalogDraft) {
  return {
    tool_catalog_max_count: draft.toolCatalogMaxCount,
    tool_catalog_max_bytes: draft.toolCatalogMaxMiB * CATALOG_LIMITS[1].unit,
    tool_definition_max_bytes: draft.toolDefinitionMaxKiB * CATALOG_LIMITS[2].unit
  } satisfies McpServerUpdatePayload;
}
