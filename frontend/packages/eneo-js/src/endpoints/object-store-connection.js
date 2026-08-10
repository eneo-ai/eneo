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
    },

    /**
     * Switch to an S3-compatible destination that already holds a copy of the
     * content namespace. The previous destination is archived for switch-back.
     * @param {import('../types/resources').ObjectStoreConnectionCreate} destination
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').ObjectStoreConnection>}
     */
    replaceDestination: async (destination) => {
      return await client.fetch("/api/v1/admin/object-store-connection/destination", {
        method: "post",
        requestBody: { "application/json": destination }
      });
    },

    /**
     * Return to the archived previous destination using its stored credentials.
     * The revision names the archive the administrator saw; the backend
     * refuses if a concurrent change replaced it.
     * @param {number} expectedPreviousRevision
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').ObjectStoreConnection>}
     */
    switchBackDestination: async (expectedPreviousRevision) => {
      return await client.fetch("/api/v1/admin/object-store-connection/destination/switch-back", {
        method: "post",
        requestBody: {
          "application/json": { expected_previous_revision: expectedPreviousRevision }
        }
      });
    },

    /**
     * Forget the archived previous destination. The bucket is never touched.
     * The revision names the archive the administrator saw; the backend
     * refuses if a concurrent change replaced it.
     * @param {number} expectedRevision
     * @throws {EneoError}
     * @returns {Promise<void>}
     */
    forgetPreviousDestination: async (expectedRevision) => {
      await client.fetch("/api/v1/admin/object-store-connection/previous", {
        method: "delete",
        params: { query: { expected_revision: expectedRevision } }
      });
    }
  };
}

/** @typedef {import('../client/client').EneoError} EneoError */
