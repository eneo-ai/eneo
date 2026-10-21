import { Package, Server, Sparkles } from "lucide-react";
import { getCapability } from "@/features/capabilities/capabilities";
import type { Schema } from "@/lib/api/models";

export type BundledTool = Schema<"BundledToolPublic">;
export type RuntimeStatus = Schema<"RuntimeStatus">;

/**
 * Where a server's tools run: Eneo itself (a built-in provider over one of
 * its loopback servers), the tool runtime shipped with Eneo, or an external
 * MCP server. One glyph and label (message key) per kind, shared by every
 * admin surface that names a source.
 */
export type SourceKind = "internal" | "bundled" | "external";

export const SOURCE_KINDS: Record<SourceKind, { icon: typeof Server; label: string }> = {
  internal: { icon: Sparkles, label: "mcp_auth_internal" },
  bundled: { icon: Package, label: "mcp_auth_bundled" },
  external: { icon: Server, label: "tools_source_external" }
};

/** The kind of source a server row is, decided by its auth type, never its name. */
export function sourceKindOf(httpAuthType: string | null | undefined): SourceKind {
  if (httpAuthType === "internal") return "internal";
  if (httpAuthType === "bundled") return "bundled";
  return "external";
}

/**
 * General (per-space) servers the runtime offers, by their tool key, with
 * their message keys. Every runtime tool is a function today; these entries
 * only name rows added while the tool was still a general server, which
 * keep working until retired.
 */
export const BUNDLED_SERVERS: Record<string, { label: string; description: string }> = {
  compute: { label: "tools_bundled_compute", description: "tools_bundled_compute_description" },
  charts: { label: "tools_bundled_charts", description: "tools_bundled_charts_description" }
};

type ServerLike = { http_auth_type: string; http_url: string; purpose?: string | null };

/** The runtime tool a bundled row serves (the last segment of its URL), or null. */
export function bundledToolOf(server: ServerLike): string | null {
  if (server.http_auth_type !== "bundled") return null;
  const tool = server.http_url.replace(/\/+$/, "").split("/").pop();
  return tool || null;
}

/**
 * The message keys naming a bundled row: a capability provider is named after
 * its function, a general server after its tool. Null for every other server,
 * whose own name and description are shown. The backend seeds the stored name
 * in English; the UI shows Eneo's own name in the reader's language.
 */
export function bundledIdentity(server: ServerLike): { name: string; description?: string } | null {
  const tool = bundledToolOf(server);
  if (tool === null) return null;
  const capability = getCapability(server.purpose);
  if (capability) return { name: capability.purpose, description: capability.bundledDescription };
  const general = BUNDLED_SERVERS[tool];
  return general ? { name: general.label, description: general.description } : { name: tool };
}

const STATE_KEYS: Record<string, string> = {
  not_configured: "tools_runtime_not_configured",
  ready: "tools_runtime_ready",
  unreachable: "tools_runtime_unreachable",
  unauthorized: "tools_runtime_unauthorized",
  unverified: "tools_runtime_unverified"
};

const WARNING_KEYS: Record<string, string> = {
  version_mismatch: "tools_runtime_mismatch",
  revision_mismatch: "tools_runtime_mismatch",
  unverified: "tools_runtime_unverified",
  confinement_unavailable: "tools_runtime_confinement",
  file_origin_unreachable: "tools_runtime_file_origin",
  file_origin_not_allowed: "tools_runtime_file_origin",
  file_origin_unknown: "tools_runtime_file_origin"
};

/** What to tell an administrator about the runtime: its state, then each warning once (message keys). */
export function runtimeMessageKeys(status: RuntimeStatus): string[] {
  return [
    ...new Set([
      STATE_KEYS[status.state ?? ""] ?? "tools_runtime_unverified",
      ...(status.warnings ?? []).flatMap((warning) =>
        WARNING_KEYS[warning] ? [WARNING_KEYS[warning]] : []
      )
    ])
  ];
}
