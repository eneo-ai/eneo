/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initObjectStoreConnection(client) {
  return {
    /**
     * Get the deployment-wide S3-compatible destination without credentials.
     * Session-backed platform administrators only.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').ObjectStoreConnection>}
     */
    get: async () => {
      return await client.fetch("/api/v1/admin/object-store-connection", {
        method: "get"
      });
    },

    /**
     * Test and save the first deployment-wide S3-compatible destination.
     * @param {import('../types/resources').ObjectStoreConnectionCreate} connection
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').ObjectStoreConnection>}
     */
    create: async (connection) => {
      return await client.fetch("/api/v1/admin/object-store-connection", {
        method: "post",
        requestBody: { "application/json": connection }
      });
    },

    /**
     * Test and replace credentials without changing the destination.
     * @param {import('../types/resources').ObjectStoreCredentialRotation} credentials
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').ObjectStoreConnection>}
     */
    rotateCredentials: async (credentials) => {
      return await client.fetch("/api/v1/admin/object-store-connection/credentials", {
        method: "put",
        requestBody: { "application/json": credentials }
      });
    }
  };
}

/** @typedef {import('../client/client').EneoError} EneoError */
