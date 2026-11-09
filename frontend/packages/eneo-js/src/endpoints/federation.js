/**
 * The authenticated organisation's sign-in (SSO) settings, for its admins.
 * The operator registers the identity provider; an admin reads it and changes
 * the label, client ID, client secret and allowed email domains. The secret is
 * write-only. The organisation is always the caller's: never a parameter.
 *
 * @param {import('../client/client').Client} client
 */
export function initFederation(client) {
  return {
    /**
     * @returns {Promise<import('../types/resources').FederationAdminView>}
     */
    get: async () => {
      return await client.fetch("/api/v1/admin/federation", { method: "get" });
    },

    /**
     * Change the settings that `patch.revision` was read with; an older
     * revision is refused with 409.
     * @param {import('../types/resources').FederationAdminPatch} patch
     * @returns {Promise<import('../types/resources').FederationAdminView>}
     */
    update: async (patch) => {
      return await client.fetch("/api/v1/admin/federation", {
        method: "patch",
        requestBody: { "application/json": patch }
      });
    }
  };
}
