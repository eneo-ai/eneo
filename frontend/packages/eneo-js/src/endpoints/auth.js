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
     * @param {string} [params.state] - Optional state parameter
     * @param {string} [params.bindingChallenge] - Base64url S256 hash of a secret the
     *   caller keeps (at least 32 random bytes); the callback then needs that secret as
     *   `bindingVerifier`
     * @returns {Promise<import("../types/resources").InitiateAuthResponse>}
     */
    initiateAuth: async ({ tenant, state, bindingChallenge }) => {
      return await client.fetch("/api/v1/auth/initiate", {
        method: "get",
        params: {
          query: {
            tenant,
            ...(state && { state }),
            // An empty value is sent too, so the backend refuses it instead of
            // starting an unbound sign-in.
            ...(bindingChallenge != null && { binding_challenge: bindingChallenge })
          }
        }
      });
    },

    /**
     * Handle OIDC callback
     * @param {Object} params
     * @param {string} params.code - Authorization code from IdP
     * @param {string} params.state - State parameter for CSRF protection
     * @param {string} [params.codeVerifier] - Ignored by the backend, which keeps the PKCE verifier itself
     * @param {string} [params.iss] - The provider's `iss` redirect parameter (RFC 9207), when it sent one
     * @param {string} [params.bindingVerifier] - The secret behind the `bindingChallenge`
     *   sent at initiate; required when one was sent
     * @returns {Promise<import("../types/resources").AccessTokenResponse>}
     */
    handleAuthCallback: async ({ code, state, codeVerifier, iss, bindingVerifier }) => {
      /** @type {import("../types/resources").AccessTokenResponse} */
      // @ts-ignore - response type is unknown in schema
      const res = await client.fetch("/api/v1/auth/callback", {
        method: "post",
        requestBody: {
          "application/json": {
            code,
            state,
            ...(codeVerifier && { code_verifier: codeVerifier }),
            ...(iss && { iss }),
            ...(bindingVerifier != null && { binding_verifier: bindingVerifier })
          }
        }
      });
      return res;
    }
  };
}
