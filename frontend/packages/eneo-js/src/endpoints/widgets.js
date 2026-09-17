/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').Widget} Widget */
/** @typedef {import('../types/resources').WidgetPolicy} WidgetPolicy */
/** @typedef {import('../types/resources').WidgetUsage} WidgetUsage */
/** @typedef {import('../types/resources').WidgetPreviewToken} WidgetPreviewToken */

/**
 * Admin side of embeddable widgets: the objects editors configure in a space
 * and the tenant policy admins set. The visitor-facing surface lives in
 * `createWidgetClient` (widget.js).
 *
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initWidgets(client) {
  return {
    /**
     * List the widgets configured in a space.
     * @param {{spaceId: string}} params
     * @returns {Promise<Widget[]>}
     * @throws {EneoError}
     */
    list: async ({ spaceId }) => {
      const res = await client.fetch("/api/v1/spaces/{space_id}/widgets/", {
        method: "get",
        params: { path: { space_id: spaceId } }
      });
      return res.items;
    },

    /**
     * Create a draft widget for an assistant in the space.
     * @param {{spaceId: string} & import('../types/fetch').JSONRequestBody<"post", "/api/v1/spaces/{space_id}/widgets/">} params
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    create: async ({ spaceId, ...body }) => {
      const res = await client.fetch("/api/v1/spaces/{space_id}/widgets/", {
        method: "post",
        params: { path: { space_id: spaceId } },
        requestBody: { "application/json": body }
      });
      return res;
    },

    /**
     * @param {{id: string}} widget
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    get: async ({ id }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Partial update; visitor-facing changes bump the token generation.
     * @param {Object} params
     * @param {{id: string}} params.widget
     * @param {import('../types/fetch').JSONRequestBody<"patch", "/api/v1/widgets/{id}/">} params.update
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    update: async ({ widget, update }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/", {
        method: "patch",
        params: { path: { id: widget.id } },
        requestBody: { "application/json": update }
      });
      return res;
    },

    /**
     * Tenant admins only; fails with the blockers when configuration is incomplete.
     * @param {{id: string}} widget
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    activate: async ({ id }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/activate/", {
        method: "post",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * The kill switch: takes effect immediately for every visitor.
     * @param {{id: string}} widget
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    pause: async ({ id }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/pause/", {
        method: "post",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * @param {{id: string}} widget
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    archive: async ({ id }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/archive/", {
        method: "post",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Daily usage series and today's budget consumption.
     * @param {{id: string; days?: number}} params
     * @returns {Promise<WidgetUsage>}
     * @throws {EneoError}
     */
    usage: async ({ id, days }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/usage/", {
        method: "get",
        params: { path: { id }, query: days !== undefined ? { days } : undefined }
      });
      return res;
    },

    /**
     * Token that lets the admin page frame the real embed page of a draft or paused widget.
     * @param {{id: string}} widget
     * @returns {Promise<WidgetPreviewToken>}
     * @throws {EneoError}
     */
    previewToken: async ({ id }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/preview-token/", {
        method: "post",
        params: { path: { id } }
      });
      return res;
    },

    policy: {
      /**
       * Tenant-wide limits for widgets (admins only).
       * @returns {Promise<WidgetPolicy>}
       * @throws {EneoError}
       */
      get: async () => {
        const res = await client.fetch("/api/v1/admin/widget-policy/", { method: "get" });
        return res;
      },

      /**
       * @param {import('../types/fetch').JSONRequestBody<"patch", "/api/v1/admin/widget-policy/">} update
       * @returns {Promise<WidgetPolicy>}
       * @throws {EneoError}
       */
      update: async (update) => {
        const res = await client.fetch("/api/v1/admin/widget-policy/", {
          method: "patch",
          requestBody: { "application/json": update }
        });
        return res;
      }
    }
  };
}
