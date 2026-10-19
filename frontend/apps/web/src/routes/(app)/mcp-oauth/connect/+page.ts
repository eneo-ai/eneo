export const load = async (event) => {
  const { eneo } = await event.parent();
  const serverId = event.url.searchParams.get("server");

  const connections = serverId ? await eneo.mcpOauth.myConnections() : [];
  const connection = connections.find((c) => c.mcp_server_id === serverId) ?? null;

  return {
    serverId,
    connection,
    // Present when the vendor sent the browser back here through the
    // full-page callback; the page finishes the authorization with them.
    code: event.url.searchParams.get("code"),
    state: event.url.searchParams.get("state"),
    iss: event.url.searchParams.get("iss"),
    oauthError:
      event.url.searchParams.get("error_description") ?? event.url.searchParams.get("error")
  };
};
