export interface AIBuilderMcpToolLike {
  id: string;
  name?: string | null;
}

export interface AIBuilderMcpServerLike {
  id: string;
  name?: string | null;
  tools?: AIBuilderMcpToolLike[] | null;
}

export interface AIBuilderMcpResourceLabelMaps {
  serverLabels: Map<string, string>;
  toolLabels: Map<string, string>;
}

export function buildAIBuilderMcpResourceLabelMaps(
  servers: AIBuilderMcpServerLike[]
): AIBuilderMcpResourceLabelMaps {
  const serverLabels = new Map<string, string>();
  const toolLabels = new Map<string, string>();

  for (const server of servers) {
    const serverLabel = resourceLabel(server.id, server.name);
    serverLabels.set(server.id, serverLabel);

    for (const tool of server.tools ?? []) {
      const toolLabel = resourceLabel(tool.id, tool.name);
      toolLabels.set(tool.id, `${serverLabel}: ${toolLabel}`);
    }
  }

  return { serverLabels, toolLabels };
}

function resourceLabel(id: string, name?: string | null): string {
  const cleanName = name?.trim();
  return cleanName || id;
}
