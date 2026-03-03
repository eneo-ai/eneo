/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initFlows(client) {
  /** @param {string} path @param {object} options */
  const _fetch = (path, options) => /** @type {any} */ (client).fetch(path, options);

  return {
    /**
     * Create a new Flow
     * @param {{spaceId: string, name: string, description?: string, steps?: any[], metadata_json?: any, data_retention_days?: number}} flow
     * @throws {IntricError}
     */
    create: async (flow) => {
      const { spaceId, name, description, steps = [], metadata_json, data_retention_days } = flow;
      return _fetch("/api/v1/flows/", {
        method: "post",
        requestBody: {
          "application/json": {
            space_id: spaceId,
            name,
            description,
            steps,
            metadata_json,
            data_retention_days
          }
        }
      });
    },

    /**
     * List flows in a space
     * @param {{spaceId: string, limit?: number, offset?: number}} params
     * @throws {IntricError}
     */
    list: async ({ spaceId, limit = 50, offset = 0 }) => {
      return _fetch("/api/v1/flows/", {
        method: "get",
        params: { query: { space_id: spaceId, limit, offset } }
      });
    },

    /**
     * Get a flow by id
     * @param {{id: string}} flow
     * @throws {IntricError}
     */
    get: async (flow) => {
      return _fetch(`/api/v1/flows/${flow.id}/`, { method: "get" });
    },

    /**
     * Update a flow
     * @param {{flow: {id: string}, update: object}} params
     * @throws {IntricError}
     */
    update: async ({ flow, update }) => {
      return _fetch(`/api/v1/flows/${flow.id}/`, {
        method: "patch",
        requestBody: { "application/json": update }
      });
    },

    /**
     * Delete a flow
     * @param {{id: string}} flow
     * @returns {Promise<true>}
     * @throws {IntricError}
     */
    delete: async (flow) => {
      await _fetch(`/api/v1/flows/${flow.id}/`, { method: "delete" });
      return true;
    },

    /**
     * Publish a flow
     * @param {{id: string}} flow
     * @throws {IntricError}
     */
    publish: async (flow) => {
      return _fetch(`/api/v1/flows/${flow.id}/publish/`, { method: "post" });
    },

    /**
     * Unpublish a flow (return to draft)
     * @param {{id: string}} flow
     * @throws {IntricError}
     */
    unpublish: async (flow) => {
      return _fetch(`/api/v1/flows/${flow.id}/unpublish/`, { method: "post" });
    },

    /**
     * Get the graph representation of a flow
     * @param {{id: string, run_id?: string}} params
     * @throws {IntricError}
     */
    graph: async ({ id, run_id }) => {
      const query = run_id ? { run_id } : {};
      return _fetch(`/api/v1/flows/${id}/graph/`, {
        method: "get",
        params: { query }
      });
    },

    assistants: {
      /**
       * Create a flow-managed assistant owned by the flow.
       * @param {{id: string, name: string}} params
       * @throws {IntricError}
       */
      create: async ({ id, name }) => {
        return _fetch(`/api/v1/flows/${id}/assistants/`, {
          method: "post",
          requestBody: { "application/json": { name } }
        });
      },

      /**
       * Get a flow-managed assistant.
       * @param {{id: string, assistantId: string}} params
       * @throws {IntricError}
       */
      get: async ({ id, assistantId }) => {
        return _fetch(`/api/v1/flows/${id}/assistants/${assistantId}/`, {
          method: "get"
        });
      },

      /**
       * Update a flow-managed assistant.
       * @param {{id: string, assistantId: string, update: object}} params
       * @throws {IntricError}
       */
      update: async ({ id, assistantId, update }) => {
        const body = /** @type {{description?: string | null} & Record<string, any>} */ ({
          ...update
        });
        if (typeof body.description === "string" && body.description.trim() === "") {
          body.description = null;
        }
        return _fetch(`/api/v1/flows/${id}/assistants/${assistantId}/`, {
          method: "patch",
          requestBody: { "application/json": body }
        });
      },

      /**
       * Delete a flow-managed assistant.
       * @param {{id: string, assistantId: string}} params
       * @returns {Promise<true>}
       * @throws {IntricError}
       */
      delete: async ({ id, assistantId }) => {
        await _fetch(`/api/v1/flows/${id}/assistants/${assistantId}/`, {
          method: "delete"
        });
        return true;
      }
    },

    runs: {
      /**
       * Create a flow run
       * @param {{flow: {id: string}, input_payload_json?: any, file_ids?: string[]}} params
       * @throws {IntricError}
       */
      create: async ({ flow, input_payload_json, file_ids }) => {
        return _fetch(`/api/v1/flows/${flow.id}/runs/`, {
          method: "post",
          requestBody: {
            "application/json": {
              input_payload_json,
              ...(file_ids?.length ? { file_ids } : {})
            }
          }
        });
      },

      /**
       * List runs for a flow
       * @param {{flowId: string, limit?: number, offset?: number}} params
       * @throws {IntricError}
       */
      list: async ({ flowId, limit = 50, offset = 0 }) => {
        return _fetch("/api/v1/flow-runs/", {
          method: "get",
          params: { query: { flow_id: flowId, limit, offset } }
        });
      },

      /**
       * Get a specific flow run
       * @param {{id: string}} run
       * @throws {IntricError}
       */
      get: async (run) => {
        return _fetch(`/api/v1/flow-runs/${run.id}/`, { method: "get" });
      },

      /**
       * Cancel a flow run
       * @param {{id: string}} run
       * @throws {IntricError}
       */
      cancel: async (run) => {
        return _fetch(`/api/v1/flow-runs/${run.id}/cancel/`, { method: "post" });
      },

      /**
       * Redispatch a stale queued flow run
       * @param {{id: string}} run
       * @returns {Promise<import('../types/resources').FlowRunRedispatchResult>}
       * @throws {IntricError}
       */
      redispatch: async (run) => {
        return _fetch(`/api/v1/flow-runs/${run.id}/redispatch/`, { method: "post" });
      },

      /**
       * Get evidence for a flow run
       * @param {{id: string}} run
       * @throws {IntricError}
       */
      evidence: async (run) => {
        return _fetch(`/api/v1/flow-runs/${run.id}/evidence/`, { method: "get" });
      }
    }
  };
}
