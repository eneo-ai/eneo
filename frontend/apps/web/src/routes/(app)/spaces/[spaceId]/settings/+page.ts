/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

export const load = async (event) => {
  const { eneo, currentSpace } = await event.parent();

  const [models, security, mcpServers] = await Promise.all([
    eneo.models.list({ space: currentSpace }),
    eneo.securityClassifications.list(),
    eneo.mcpServers.listSettings()
  ]);

  // Filter to only tenant-enabled servers
  const enabledMCPServers = mcpServers.items
    .filter((server) => server.is_org_enabled)
    .map((server) => ({
      id: server.id, // Use server.id instead of server.mcp_server_id
      name: server.name, // Use server.name instead of server.mcp_server_name
      description: server.description,
      http_url: server.http_url,
      http_auth_type: server.http_auth_type,
      tags: server.tags,
      icon_url: server.icon_url,
      security_classification: server.security_classification ?? null,
      tools: server.tools ?? []
    }));

  return {
    models,
    classifications: security.security_classifications,
    isSecurityEnabled: security.security_enabled,
    mcpServers: enabledMCPServers
  };
};
