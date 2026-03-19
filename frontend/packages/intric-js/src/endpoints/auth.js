/**
 * @param {import('../client/client').Client} client
 */
export function initAuth(client) {
  return {
    /**
     * List all active tenants for tenant selector
     * @returns {Promise<import("../types/resources").TenantListResponse>}
     */
    listTenants: async () => {
      return await client.fetch("/api/v1/auth/tenants", {
        method: "get"
      });
    },

    /**
     * Initiate OIDC authentication for a tenant
     * @param {Object} params
     * @param {string} params.tenant - Tenant slug
     * @param {string} params.redirectUri - Redirect URI after authentication
     * @param {string} [params.state] - Optional state parameter
     * @returns {Promise<import("../types/resources").InitiateAuthResponse>}
     */
    initiateAuth: async ({ tenant, redirectUri, state }) => {
      return await client.fetch("/api/v1/auth/initiate", {
        method: "get",
        params: {
          query: {
            tenant,
            // @ts-ignore - redirect_uri is accepted by the backend but not in the generated schema
            redirect_uri: redirectUri,
            ...(state && { state })
          }
        }
      });
    },

    /**
     * Handle OIDC callback
     * @param {Object} params
     * @param {string} params.code - Authorization code from IdP
     * @param {string} params.state - State parameter for CSRF protection
     * @param {string} [params.codeVerifier] - PKCE code verifier (if applicable)
     * @returns {Promise<import("../types/resources").AccessTokenResponse>}
     */
    handleAuthCallback: async ({ code, state, codeVerifier }) => {
      /** @type {import("../types/resources").AccessTokenResponse} */
      // @ts-ignore - response type is unknown in schema
      const res = await client.fetch("/api/v1/auth/callback", {
        method: "post",
        requestBody: {
          "application/json": {
            code,
            state,
            ...(codeVerifier && { code_verifier: codeVerifier })
          }
        }
      });
      return res;
    }
  };
}
