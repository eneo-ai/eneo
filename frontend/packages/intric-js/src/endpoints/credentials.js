/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @typedef {Object} CredentialInfo
 * @property {string} provider
 * @property {string} masked_key
 * @property {string | null} configured_at
 * @property {"encrypted" | "plaintext"} encryption_status
 * @property {Record<string, any>} config
 */

/**
 * @typedef {Object} SetCredentialRequest
 * @property {string} api_key
 * @property {string} [endpoint]
 * @property {string} [api_version]
 * @property {string} [deployment_name]
 */

/**
 * @typedef {Object} SetCredentialResponse
 * @property {string} provider
 * @property {string} masked_key
 * @property {string} message
 * @property {string} set_at
 */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initCredentials(client) {
  return {
    /**
     * List all API credentials for the current tenant
     * @throws {IntricError}
     * @returns {Promise<{credentials: CredentialInfo[]}>}
     */
    list: async () => {
      const res = await client.fetch("/api/v1/admin/credentials/", {
        method: "get"
      });
      return res;
    },

    /**
     * Set or update API credential for a specific provider
     * @param {string} provider - Provider name (e.g., "openai", "azure", "anthropic")
     * @param {SetCredentialRequest} credential - Credential data
     * @throws {IntricError}
     * @returns {Promise<SetCredentialResponse>}
     */
    set: async (provider, credential) => {
      const res = await client.fetch("/api/v1/admin/credentials/{provider}", {
        method: "put",
        params: { path: { provider } },
        requestBody: { "application/json": credential }
      });
      return res;
    }
  };
}
