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
        method: "GET"
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
        method: "GET",
        params: {
          query: {
            tenant,
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
      return await client.fetch("/api/v1/auth/callback", {
        method: "POST",
        requestBody: {
          "application/json": {
            code,
            state,
            ...(codeVerifier && { code_verifier: codeVerifier })
          }
        }
      });
    }
  };
}
