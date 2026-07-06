/** @typedef {import('../types/resources').SecurityClassification} SecurityClassification */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initSecurityClassifications(client) {
  return {
    /**
     * Lists all security classifications on this tenant.
     * @throws {EneoError}
     * */
    list: async () => {
      const res = await client.fetch("/api/v1/security-classifications/", { method: "get" });
      return res;
    },

    /**
     * Change the hierarchy of the current classifications, from least security to highest security.
     * @param {import('../types/fetch').JSONRequestBody<"patch", "/api/v1/security-classifications/">["security_classifications"]} security_classifications
     * @throws {EneoError}
     * */
    rank: async (security_classifications) => {
      const res = await client.fetch("/api/v1/security-classifications/", {
        method: "patch",
        requestBody: {
          "application/json": {
            security_classifications
          }
        }
      });
      return res.security_classifications;
    },

    /**
     * Enable using security classifications for this tenant.
     * @throws {EneoError}
     * */
    enable: async () => {
      const res = await client.fetch("/api/v1/security-classifications/enable/", {
        method: "post",
        requestBody: {
          "application/json": {
            enabled: true
          }
        }
      });
      return res;
    },

    /**
     * Disable using security classifications for this tenant.
     * @throws {EneoError}
     * */
    disable: async () => {
      const res = await client.fetch("/api/v1/security-classifications/enable/", {
        method: "post",
        requestBody: {
          "application/json": {
            enabled: false
          }
        }
      });
      return res;
    },

    /**
     * Creates a new security classification for the current tenant.
     * @param {Object} params
     * @param {string} params.name A name for the new classification
     * @param {string} params.description A description for the new classification
     * @param {"lowest" | "highest"} [params.insertAs] Defaults to lowest
     * @returns {Promise<SecurityClassification>}
     * @throws {EneoError}
     * */
    create: async ({ name, description, insertAs }) => {
      const res = await client.fetch("/api/v1/security-classifications/", {
        method: "post",
        requestBody: {
          "application/json": {
            name,
            description,
            set_lowest_security: insertAs ? insertAs === "lowest" : true
          }
        }
      });
      return res;
    },

    /**
     * Updates the specified security classification for the current tenant.
     * @param {Object} params
     * @param {string} params.id
     * @param {string} [params.name] A name for the new classification
     * @param {string} [params.description] A description for the new classification
     * @throws {EneoError}
     * */
    update: async ({ id, name, description }) => {
      const res = await client.fetch("/api/v1/security-classifications/{id}/", {
        method: "patch",
        params: {
          path: {
            id
          }
        },
        requestBody: {
          "application/json": {
            name,
            description
          }
        }
      });
      return res;
    },

    /**
     * Delete the specified classification
     * @param {Object} params
     * @param {string} params.id
     * @throws {EneoError}
     * */
    delete: async ({ id }) => {
      await client.fetch("/api/v1/security-classifications/{id}/", {
        method: "delete",
        params: {
          path: {
            id
          }
        }
      });
    },

    /**
     * Check which resources of a space would be affect (no longer working) when the specified security classification gets applied.
     * @param {Object} params
     * @param {{id: string}} params.space
     * @param {{id: string}} params.classification
     * @throws {EneoError}
     * */
    impactAnalysis: async ({ space, classification }) => {
      const { id } = space;
      const { id: security_classification_id } = classification;
      const res = await client.fetch(
        "/api/v1/spaces/{id}/security_classification/{security_classification_id}/impact-analysis/",
        {
          method: "get",
          params: {
            path: { id, security_classification_id }
          }
        }
      );
      return res;
    }
  };
}
