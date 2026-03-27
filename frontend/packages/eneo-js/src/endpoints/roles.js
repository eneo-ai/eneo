/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').Role} Role */
/** @typedef {import('../types/resources').Permission} Permission */
/** @typedef {import('../types/resources').Tenant} Tenant */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initRoles(client) {
  return {
    /**
     * Lists all roles on this tenant.
     * @returns {Promise<{name: Permission, description: string}[]>}
     * @throws {EneoError}
     * */
    listPermissions: async () => {
      const res = await client.fetch("/api/v1/roles/permissions/", { method: "get" });
      return res;
    },

    /**
     * Lists all roles on this tenant.
     * @returns {Promise<{roles: Role[], predefined_roles: Role[]}>}
     * @throws {EneoError}
     * */
    list: async () => {
      const res = await client.fetch("/api/v1/roles/", { method: "get" });
      return {
        roles: res.roles.items,
        predefined_roles: res.predefined_roles.items
      };
    },

    /**
     * Creates a new role for the current tenant.
     * @param {Object} params
     * @param {string} params.name A name for the new role
     * @param {Permission[]} params.permissions This role's permissions
     * @returns {Promise<Role>} Returns the created role
     * @throws {EneoError}
     * */
    create: async ({ name, permissions }) => {
      const res = await client.fetch("/api/v1/roles/", {
        method: "post",
        requestBody: {
          "application/json": {
            name,
            permissions
          }
        }
      });
      return res;
    },

    /**
     * Get a role by its id.
     * @param {{id: string} | Role} role Role to get
     * @returns {Promise<Role>}
     * @throws {EneoError}
     * */
    get: async (role) => {
      const role_id = role.id;
      const res = await client.fetch("/api/v1/roles/{role_id}/", {
        method: "get",
        params: { path: { role_id } }
      });
      return res;
    },

    /**
     * Delete a role by its id.
     * @param {{id: string} | Role} role Role to delete
     * @returns {Promise<Role>} Returns the deleted role on success
     * @throws {EneoError}
     * */
    delete: async (role) => {
      const role_id = role.id;
      const res = await client.fetch("/api/v1/roles/{role_id}/", {
        method: "delete",
        params: { path: { role_id } }
      });
      return res;
    },

    /**
     * Update an existing role.
     * @param {Object} params
     * @param {{id: string} | Role} params.role Role to update
     * @param {Partial<Role>} params.update Supply properties to update.
     * @returns {Promise<Role>} Returns the updated role.
     * @throws {EneoError}
     * */
    update: async ({ role, update }) => {
      const role_id = role.id;
      const res = await client.fetch("/api/v1/roles/{role_id}/", {
        method: "post",
        params: { path: { role_id } },
        requestBody: { "application/json": update }
      });
      return res;
    }
  };
}
