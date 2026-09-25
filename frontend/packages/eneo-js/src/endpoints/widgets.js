/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').Widget} Widget */
/** @typedef {import('../types/resources').WidgetPolicy} WidgetPolicy */
/** @typedef {import('../types/resources').WidgetUsage} WidgetUsage */
/** @typedef {import('../types/resources').WidgetPreviewToken} WidgetPreviewToken */
/** @typedef {import('../types/resources').WidgetTemplate} WidgetTemplate */
/** @typedef {import('../types/resources').WidgetOverview} WidgetOverview */
/** @typedef {import('../types/resources').AdminWidgetReview} AdminWidgetReview */

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
     * Tenant admins only, member of the space or not; fails with the blockers
     * when configuration is incomplete. Pass the reviewed `revision` to be
     * refused with `widget_revision_conflict` if the widget changed since.
     * @param {{id: string, revision?: number}} params
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    activate: async ({ id, revision }) => {
      if (revision === undefined) {
        const res = await client.fetch("/api/v1/widgets/{id}/activate/", {
          method: "post",
          params: { path: { id } }
        });
        return res;
      }
      // The typed fetch cannot express an optional request body.
      const options = /** @type {any} */ ({
        method: "post",
        params: { path: { id } },
        requestBody: { "application/json": { revision } }
      });
      return await client.fetch("/api/v1/widgets/{id}/activate/", options);
    },

    /**
     * Ask a tenant admin to review and activate a draft or paused widget.
     * Asking again while a request is pending changes nothing.
     * @param {{id: string}} widget
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    requestActivation: async ({ id }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/activation-request/", {
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
    withdrawActivationRequest: async ({ id }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/activation-request/", {
        method: "delete",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Send a pending request back to the editors with what needs to change
     * (tenant admins only); fails with `widget_activation_request_missing`
     * when nothing is pending. The API normalises the reason (see
     * `WidgetActivationDecline.reason`) and needs at least 10 visible
     * characters.
     * @param {{id: string, reason: string}} params
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    declineActivationRequest: async ({ id, reason }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/activation-request/decline/", {
        method: "post",
        params: { path: { id } },
        requestBody: { "application/json": { reason } }
      });
      return res;
    },

    /**
     * Everything an admin reviews before activating: the visitor-facing
     * settings, the target assistant with its instructions, knowledge and
     * every widget serving it, the capabilities visitors reach and recent
     * usage (admins only).
     * @param {{id: string}} widget
     * @returns {Promise<AdminWidgetReview>}
     * @throws {EneoError}
     */
    review: async ({ id }) => {
      const res = await client.fetch("/api/v1/admin/widgets/{id}/", {
        method: "get",
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
     * Token that lets a live test frame the real embed page of a draft or paused widget.
     * A tenant admin needs to be a member of the space, and the assistant published;
     * their token expires sooner (`expires_in`, 10 minutes by default) than an
     * editor's, since membership is only checked here. Without the widgets or
     * admin permission the call is refused before the widget is looked up.
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

    /**
     * Make the widget follow a template: its texts, appearance and language are
     * copied now and the template's locked groups stay in step afterwards.
     * @param {{widget: {id: string}; templateId: string; revision: number}} params
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    linkTemplate: async ({ widget, templateId, revision }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/link-template/", {
        method: "post",
        params: { path: { id: widget.id } },
        requestBody: { "application/json": { template_id: templateId, revision } }
      });
      return res;
    },

    /**
     * Stop following the template; the widget keeps its current values.
     * @param {{widget: {id: string}; revision: number}} params
     * @returns {Promise<Widget>}
     * @throws {EneoError}
     */
    detachTemplate: async ({ widget, revision }) => {
      const res = await client.fetch("/api/v1/widgets/{id}/detach-template/", {
        method: "post",
        params: { path: { id: widget.id } },
        requestBody: { "application/json": { revision } }
      });
      return res;
    },

    /**
     * Every widget in the organisation with its recent usage (admins only).
     * `space_kind` says whether the widget's space opens in space oversight
     * (only `shared` does).
     * @returns {Promise<WidgetOverview>}
     * @throws {EneoError}
     */
    overview: async () => {
      const res = await client.fetch("/api/v1/admin/widgets/", { method: "get" });
      return res;
    },

    templates: {
      /**
       * Templates of the organisation, default first (widgets permission).
       * @returns {Promise<WidgetTemplate[]>}
       * @throws {EneoError}
       */
      list: async () => {
        const res = await client.fetch("/api/v1/widget-templates/", { method: "get" });
        return res.items;
      },

      /**
       * @param {import('../types/fetch').JSONRequestBody<"post", "/api/v1/admin/widget-templates/">} template
       * @returns {Promise<WidgetTemplate>}
       * @throws {EneoError}
       */
      create: async (template) => {
        const res = await client.fetch("/api/v1/admin/widget-templates/", {
          method: "post",
          requestBody: { "application/json": template }
        });
        return res;
      },

      /**
       * @param {{id: string}} template
       * @returns {Promise<WidgetTemplate>}
       * @throws {EneoError}
       */
      get: async ({ id }) => {
        const res = await client.fetch("/api/v1/admin/widget-templates/{id}/", {
          method: "get",
          params: { path: { id } }
        });
        return res;
      },

      /**
       * @param {Object} params
       * @param {{id: string}} params.template
       * @param {import('../types/fetch').JSONRequestBody<"patch", "/api/v1/admin/widget-templates/{id}/">} params.update
       * @returns {Promise<WidgetTemplate>}
       * @throws {EneoError}
       */
      update: async ({ template, update }) => {
        const res = await client.fetch("/api/v1/admin/widget-templates/{id}/", {
          method: "patch",
          params: { path: { id: template.id } },
          requestBody: { "application/json": update }
        });
        return res;
      },

      /**
       * Publish the draft: it becomes the release widgets link to, and the
       * locked parts are written onto every widget that follows the template.
       * @param {{id: string}} template
       * @returns {Promise<WidgetTemplate>}
       * @throws {EneoError}
       */
      publish: async ({ id }) => {
        const res = await client.fetch("/api/v1/admin/widget-templates/{id}/publish/", {
          method: "post",
          params: { path: { id } }
        });
        return res;
      },

      /**
       * @param {{id: string}} template
       * @returns status 204 on success; should throw on error
       * @throws {EneoError}
       */
      delete: async ({ id }) => {
        const res = await client.fetch("/api/v1/admin/widget-templates/{id}/", {
          method: "delete",
          params: { path: { id } }
        });
        return res;
      }
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
