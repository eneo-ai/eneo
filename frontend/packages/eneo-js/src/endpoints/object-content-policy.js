/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initObjectContentPolicy(client) {
  return {
    /**
     * Get the deployment-wide object content storage policy and its effective projections.
     * Tenant administrators may read this policy.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').DeploymentPolicy>}
     */
    get: async () => {
      return await client.fetch("/api/v1/admin/object-content-policy", {
        method: "get"
      });
    },

    /**
     * Replace the deployment-wide object content storage policy.
     * Session-backed platform administrators only.
     * @param {import('../types/resources').DeploymentPolicyUpdate} policy
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').DeploymentPolicy>}
     */
    replace: async (policy) => {
      return await client.fetch("/api/v1/admin/object-content-policy", {
        method: "put",
        requestBody: { "application/json": policy }
      });
    }
  };
}

/** @typedef {import('../client/client').EneoError} EneoError */
