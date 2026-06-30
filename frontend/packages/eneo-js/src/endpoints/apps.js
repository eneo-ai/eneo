/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').App} App */
/** @typedef {import('../types/resources').AppRun} AppRun */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initApps(client) {
  return {
    /**
     * Create a new App
     * @param {({spaceId: string} & import('../types/fetch').JSONRequestBody<"post", "/api/v1/spaces/{id}/applications/apps/">)} app
     * @throws {EneoError}
     * */
    create: async (app) => {
      const { spaceId: id, name, from_template } = app;
      const res = await client.fetch("/api/v1/spaces/{id}/applications/apps/", {
        method: "post",
        params: {
          path: {
            id
          }
        },
        requestBody: {
          "application/json": { name, from_template }
        }
      });
      return res;
    },

    /**
     * Get a specific App
     * @param {{id: string}} app
     * @returns {Promise<App>}
     */
    get: async (app) => {
      const { id } = app;
      const res = await client.fetch("/api/v1/apps/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Update a specific App
     * @param {Object} params
     * @param {{id: string}} params.app
     * @param {import('../types/fetch').JSONRequestBody<"patch", "/api/v1/apps/{id}/">} params.update
     * @returns {Promise<App>}
     * @throws {EneoError}
     */
    update: async ({ app, update }) => {
      const { id } = app;
      const res = await client.fetch("/api/v1/apps/{id}/", {
        method: "patch",
        params: { path: { id } },
        requestBody: { "application/json": update }
      });
      return res;
    },

    /**
     * Delete a specific App
     * @param {{id: string}} app
     * @returns status 204 on success; should throw on error
     * @throws {EneoError}
     */
    delete: async (app) => {
      const { id } = app;
      const res = await client.fetch("/api/v1/apps/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Get the list of prompt history for an app.
     * @param  {{id: string} | App} app
     * @returns {Promise<import('../types/resources').PromptSparse[]>}
     * */
    listPrompts: async (app) => {
      const { id } = app;
      const res = await client.fetch("/api/v1/apps/{id}/prompts/", {
        method: "get",
        params: { path: { id } }
      });
      return res.items;
    },

    /**
     * Publish an app inside its space
     * @param  {{id: string} | App} app
     * @returns {Promise<App>}
     * */
    publish: async (app) => {
      const { id } = app;
      const res = await client.fetch("/api/v1/apps/{id}/publish/", {
        method: "post",
        params: {
          path: { id },
          query: { published: true }
        }
      });

      return res;
    },

    /**
     * Unpublish an app inside its space
     * @param  {{id: string} | App} app
     * @returns {Promise<App>}
     * */
    unpublish: async (app) => {
      const { id } = app;
      const res = await client.fetch("/api/v1/apps/{id}/publish/", {
        method: "post",
        params: {
          path: { id },
          query: { published: false }
        }
      });

      return res;
    },

    runs: {
      /**
       * List all runs for a specific App
       * @param {{app: {id: string}}} app
       * @returns {Promise<import('../types/resources').AppRunSparse[]>}
       * @throws {EneoError}
       */
      list: async ({ app }) => {
        const { id } = app;
        const res = await client.fetch("/api/v1/apps/{id}/runs/", {
          method: "get",
          params: { path: { id } }
        });
        return res.items;
      },

      /**
       * Create a new run for an App
       * @param {{app: {id: string}, inputs: import('../types/fetch').JSONRequestBody<"post", "/api/v1/apps/{id}/runs/">}} app
       * @returns {Promise<AppRun>}
       * @throws {EneoError}
       */
      create: async ({ app, inputs }) => {
        const { id } = app;
        const res = await client.fetch("/api/v1/apps/{id}/runs/", {
          method: "post",
          params: { path: { id } },
          requestBody: { "application/json": inputs }
        });
        return res;
      },

      /**
       * Get a specific App run
       * @param {{id: string}} run
       * @returns {Promise<AppRun>}
       * @throws {EneoError}
       */
      get: async (run) => {
        const { id } = run;
        const res = await client.fetch("/api/v1/app-runs/{id}/", {
          method: "get",
          params: { path: { id } }
        });
        return res;
      },

      /**
       * Delet a specific App run
       * @param {{id: string}} run
       * @returns nothing on success, throws on failure
       * @throws {EneoError}
       */
      delete: async (run) => {
        const { id } = run;
        const res = await client.fetch("/api/v1/app-runs/{id}/", {
          method: "delete",
          params: { path: { id } }
        });
        return res;
      }
    }
  };
}
