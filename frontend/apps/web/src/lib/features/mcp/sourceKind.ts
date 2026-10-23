/**
 * Where a server's tools run: Eneo itself (a built-in provider over one of
 * its loopback servers), the tool runtime shipped with Eneo, or an external
 * MCP server. One glyph and label per kind, shared by every admin surface
 * that names a source.
 */
import { Package, Server, Sparkles } from "@lucide/svelte";
import { m } from "$lib/paraglide/messages";

export type SourceKind = "internal" | "bundled" | "external";

export const SOURCE_KINDS: Record<SourceKind, { icon: typeof Server; label: () => string }> = {
  internal: { icon: Sparkles, label: m.mcp_auth_internal },
  bundled: { icon: Package, label: m.mcp_auth_bundled },
  external: { icon: Server, label: m.tools_source_external }
};

/** The kind of source a server row is, decided by its auth type, never its name. */
export function sourceKindOf(httpAuthType: string | null | undefined): SourceKind {
  if (httpAuthType === "internal") return "internal";
  if (httpAuthType === "bundled") return "bundled";
  return "external";
}

/** Glyph and label of the kind of source a server row is. */
export function sourceKind(httpAuthType: string | null | undefined) {
  return SOURCE_KINDS[sourceKindOf(httpAuthType)];
}
