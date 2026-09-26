/**
 * Turn a raw tool identifier into a readable label: drop a server/ prefix,
 * swap separators for spaces, and capitalize. `search_knowledge_base` →
 * `Search knowledge base`, `jira/create_issue` → `Jira create issue`.
 */
export function humanizeToolName(name: string): string {
  const words = name.replace(/[/_-]+/g, " ").trim();
  if (!words) return name;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

type Translate = (key: string, values?: Record<string, string>) => string;
type ToolLike = {
  toolName: string;
  input?: unknown;
  /** Set on parts mapped from a saved session (map-session.ts). */
  providerMetadata?: unknown;
  /** AI SDK v6 keeps a streamed tool's metadata here (input phase)… */
  callProviderMetadata?: unknown;
  /** …and here (output phase). */
  resultProviderMetadata?: unknown;
};

/**
 * The `eneo` provider metadata of a tool part (server_name, title, purpose,
 * approved), wherever the AI SDK put it: saved sessions use
 * `providerMetadata`, live streams `callProviderMetadata` /
 * `resultProviderMetadata`.
 */
export function eneoToolMetadata(part: ToolLike): Record<string, unknown> {
  for (const provider of [
    part.providerMetadata,
    part.callProviderMetadata,
    part.resultProviderMetadata
  ]) {
    const eneo =
      provider && typeof provider === "object" && "eneo" in provider
        ? (provider as { eneo?: unknown }).eneo
        : null;
    if (eneo && typeof eneo === "object") return eneo as Record<string, unknown>;
  }
  return {};
}

function metadata(part: ToolLike): {
  serverName: string;
  title: string | null;
  purpose: string | null;
} {
  const values = eneoToolMetadata(part);
  const server = "server_name" in values ? values.server_name : null;
  const title = "title" in values ? values.title : null;
  const purpose = "purpose" in values ? values.purpose : null;
  return {
    serverName: typeof server === "string" ? server : "",
    title: typeof title === "string" ? title : null,
    purpose: typeof purpose === "string" ? purpose : null
  };
}

function argumentsOf(part: ToolLike): Record<string, unknown> {
  return part.input && typeof part.input === "object" && !Array.isArray(part.input)
    ? (part.input as Record<string, unknown>)
    : {};
}

function searchQuery(args: Record<string, unknown>): string | null {
  const value = args.query ?? args.q;
  if (typeof value !== "string") return null;
  const query = value.trim();
  return query ? (query.length > 60 ? `${query.slice(0, 60)}…` : query) : null;
}

export function isSkillCall(part: ToolLike): boolean {
  return metadata(part).serverName === "skills";
}

export function skillName(part: ToolLike): string {
  return metadata(part).title ?? humanizeToolName(part.toolName);
}

/** Human-facing names for Eneo tools and capability calls; external MCP titles stay intact. */
export function toolPresentation(part: ToolLike, t: Translate, done: boolean) {
  const { serverName, title, purpose } = metadata(part);
  const args = argumentsOf(part);
  const query = searchQuery(args);
  if (serverName === "skills") {
    return { label: t("tool_activate_skill", { name: skillName(part) }), server: t("skills") };
  }

  const suffix = done ? "_done" : "";
  if (serverName === "knowledge") {
    const key: Record<string, string> = {
      search_knowledge: query
        ? `tool_search_knowledge_query${suffix}`
        : `tool_search_knowledge${suffix}`,
      list_knowledge_sources: `tool_list_knowledge_sources${suffix}`,
      read_source: `tool_read_source${suffix}`,
      describe_source: `tool_describe_source${suffix}`
    };
    const label = key[part.toolName];
    if (label) return { label: t(label, query ? { query } : undefined), server: t("knowledge") };
  }
  if (serverName === "files" && part.toolName === "read_file") {
    return { label: t(`tool_read_file${suffix}`), server: t("internal_files_server") };
  }
  if (purpose === "web_search") {
    return {
      label: t(
        query ? `tool_web_search_query${suffix}` : `tool_web_search${suffix}`,
        query ? { query } : undefined
      ),
      server: t("web_search"),
      provider: serverName && serverName !== "web_search" ? serverName : null
    };
  }
  if (purpose === "image_generation" || serverName === "image_generation") {
    const editing = Array.isArray(args.reference_images) && args.reference_images.length > 0;
    return {
      label: t(`tool_${editing ? "edit" : "generate"}_image${suffix}`),
      server: t("image_generation"),
      provider: serverName && serverName !== "image_generation" ? serverName : null
    };
  }
  return {
    label: title ?? humanizeToolName(part.toolName),
    server: serverName || null,
    provider: null
  };
}
