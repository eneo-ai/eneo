/** @typedef {import('../types/resources').AssistantTemplate} AssistantTemplate */
/** @typedef {import('../types/resources').AppTemplate} AppTemplate */

import { EneoError } from "../client/client.js";

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initTemplates(client) {
  return {
    /**
     * @overload `{includeDetails: true}` requires super user privileges.
     * @param {{filter: "assistants"}} params
     * @return {Promise<AssistantTemplate[]>}
     *
     * @overload
     * @param {{filter: "apps"}} params
     * @return {Promise<AppTemplate[]>}
     *
     * @overload
     * @param {{filter: never}} [params]
     * @return {Promise<(AssistantTemplate | AppTemplate)[]>}
     *
     * @param {{filter: "assistants" | "apps"}} [params]
     * @returns {Promise<(AssistantTemplate | AppTemplate)[]>}
     * @throws {EneoError}
     * */
    list: async (params) => {
      if (params) {
        if (params.filter === "apps") {
          const res = await client.fetch("/api/v1/templates/apps/", {
            method: "get"
          });
          return res.items;
        } else if (params.filter === "assistants") {
          const res = await client.fetch("/api/v1/templates/assistants/", {
            method: "get"
          });
          return res.items;
        } else {
          throw new EneoError(
            `Template filter option "${params.filter}" does not exist`,
            "CONNECTION",
            0,
            0
          );
        }
      }
      const res = await client.fetch("/api/v1/templates/", {
        method: "get"
      });
      return res.items;
    },

    /**
     * Admin methods for template management (requires admin permissions)
     */
    admin: {
      /**
       * List all assistant templates for the tenant
       * @throws {EneoError}
       */
      listAssistants: async () => {
        const res = await client.fetch("/api/v1/admin/templates/assistants/", {
          method: "get"
        });
        return res;
      },

      /**
       * List all app templates for the tenant
       * @throws {EneoError}
       */
      listApps: async () => {
        const res = await client.fetch("/api/v1/admin/templates/apps/", {
          method: "get"
        });
        return res;
      },

      /**
       * List deleted assistant templates
       * @throws {EneoError}
       */
      listDeletedAssistants: async () => {
        const res = await client.fetch("/api/v1/admin/templates/assistants/deleted", {
          method: "get"
        });
        return res;
      },

      /**
       * List deleted app templates
       * @throws {EneoError}
       */
      listDeletedApps: async () => {
        const res = await client.fetch("/api/v1/admin/templates/apps/deleted", {
          method: "get"
        });
        return res;
      },

      /**
       * Create a new assistant template
       * @param {any} data Template data
       * @throws {EneoError}
       */
      createAssistant: async (data) => {
        const res = await client.fetch("/api/v1/admin/templates/assistants/", {
          method: "post",
          requestBody: { "application/json": data }
        });
        return res;
      },

      /**
       * Create a new app template
       * @param {any} data Template data
       * @throws {EneoError}
       */
      createApp: async (data) => {
        const res = await client.fetch("/api/v1/admin/templates/apps/", {
          method: "post",
          requestBody: { "application/json": data }
        });
        return res;
      },

      /**
       * Update an assistant template
       * @param {string} id Template ID
       * @param {any} data Updated template data
       * @throws {EneoError}
       */
      updateAssistant: async (id, data) => {
        const res = await client.fetch("/api/v1/admin/templates/assistants/{template_id}", {
          method: "patch",
          params: { path: { template_id: id } },
          requestBody: { "application/json": data }
        });
        return res;
      },

      /**
       * Update an app template
       * @param {string} id Template ID
       * @param {any} data Updated template data
       * @throws {EneoError}
       */
      updateApp: async (id, data) => {
        const res = await client.fetch("/api/v1/admin/templates/apps/{template_id}", {
          method: "patch",
          params: { path: { template_id: id } },
          requestBody: { "application/json": data }
        });
        return res;
      },

      /**
       * Delete an assistant template (soft delete)
       * @param {string} id Template ID
       * @throws {EneoError}
       */
      deleteAssistant: async (id) => {
        const res = await client.fetch("/api/v1/admin/templates/assistants/{template_id}", {
          method: "delete",
          params: { path: { template_id: id } }
        });
        return res;
      },

      /**
       * Delete an app template (soft delete)
       * @param {string} id Template ID
       * @throws {EneoError}
       */
      deleteApp: async (id) => {
        const res = await client.fetch("/api/v1/admin/templates/apps/{template_id}", {
          method: "delete",
          params: { path: { template_id: id } }
        });
        return res;
      },

      /**
       * Rollback an assistant template to its original state
       * @param {string} id Template ID
       * @throws {EneoError}
       */
      rollbackAssistant: async (id) => {
        const res = await client.fetch(
          "/api/v1/admin/templates/assistants/{template_id}/rollback",
          {
            method: "post",
            params: { path: { template_id: id } }
          }
        );
        return res;
      },

      /**
       * Rollback an app template to its original state
       * @param {string} id Template ID
       * @throws {EneoError}
       */
      rollbackApp: async (id) => {
        const res = await client.fetch("/api/v1/admin/templates/apps/{template_id}/rollback", {
          method: "post",
          params: { path: { template_id: id } }
        });
        return res;
      },

      /**
       * Restore a soft-deleted assistant template
       * @param {string} id Template ID
       * @throws {EneoError}
       */
      restoreAssistant: async (id) => {
        const res = await client.fetch("/api/v1/admin/templates/assistants/{template_id}/restore", {
          method: "post",
          params: { path: { template_id: id } }
        });
        return res;
      },

      /**
       * Restore a soft-deleted app template
       * @param {string} id Template ID
       * @throws {EneoError}
       */
      restoreApp: async (id) => {
        const res = await client.fetch("/api/v1/admin/templates/apps/{template_id}/restore", {
          method: "post",
          params: { path: { template_id: id } }
        });
        return res;
      },

      /**
       * Permanently delete an assistant template (hard delete)
       * @param {string} id Template ID
       * @throws {EneoError}
       */
      permanentDeleteAssistant: async (id) => {
        const res = await client.fetch(
          "/api/v1/admin/templates/assistants/{template_id}/permanent",
          {
            method: "delete",
            params: { path: { template_id: id } }
          }
        );
        return res;
      },

      /**
       * Permanently delete an app template (hard delete)
       * @param {string} id Template ID
       * @throws {EneoError}
       */
      permanentDeleteApp: async (id) => {
        const res = await client.fetch("/api/v1/admin/templates/apps/{template_id}/permanent", {
          method: "delete",
          params: { path: { template_id: id } }
        });
        return res;
      },

      /**
       * Toggle assistant template as featured/default
       * @param {string} id Template ID
       * @param {boolean} isDefault Whether to mark as featured
       * @throws {EneoError}
       */
      toggleDefaultAssistant: async (id, isDefault) => {
        const res = await client.fetch("/api/v1/admin/templates/assistants/{template_id}/default", {
          method: "patch",
          params: { path: { template_id: id } },
          requestBody: { "application/json": { is_default: isDefault } }
        });
        return res;
      },

      /**
       * Toggle app template as featured/default
       * @param {string} id Template ID
       * @param {boolean} isDefault Whether to mark as featured
       * @throws {EneoError}
       */
      toggleDefaultApp: async (id, isDefault) => {
        const res = await client.fetch("/api/v1/admin/templates/apps/{template_id}/default", {
          method: "patch",
          params: { path: { template_id: id } },
          requestBody: { "application/json": { is_default: isDefault } }
        });
        return res;
      }
    }
  };
}
