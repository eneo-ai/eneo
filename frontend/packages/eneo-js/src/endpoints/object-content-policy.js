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
     * Get bounded deployment-wide object-content inventory facts.
     * Session-backed platform administrators only.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').ObjectContentInventory>}
     */
    getInventory: async () => {
      return await client.fetch("/api/v1/admin/object-content-inventory", {
        method: "get"
      });
    },

    /**
     * Get aggregate progress and typed failure reasons for explicit storage moves.
     * Session-backed platform administrators only.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').ObjectContentMoves>}
     */
    getMoves: async () => {
      return await client.fetch("/api/v1/admin/object-content-moves", {
        method: "get"
      });
    },

    /**
     * Queue one bounded page of eligible content for an explicit storage move.
     * Session-backed platform administrators only.
     * @param {import('../types/resources').MoveQueueRequest} request
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').MoveQueueResult>}
     */
    queueMoves: async (request) => {
      return await client.fetch("/api/v1/admin/object-content-moves", {
        method: "post",
        requestBody: { "application/json": request }
      });
    },

    /**
     * Pause or resume new storage-move claims at an expected policy revision.
     * Session-backed platform administrators only.
     * @param {import('../types/resources').MovePauseUpdate} request
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').MovePauseResult>}
     */
    setMovesPaused: async (request) => {
      return await client.fetch("/api/v1/admin/object-content-moves/pause", {
        method: "put",
        requestBody: { "application/json": request }
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
