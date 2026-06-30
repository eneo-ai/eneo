/** @typedef {import('../client/client').EneoError} EneoError */

/**
 * @typedef {Object} Icon
 * @property {string} id
 * @property {string | null} [created_at]
 * @property {string | null} [updated_at]
 */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initIcons(client) {
  return {
    /**
     * Upload an icon image file
     * @param {Object} params
     * @param {File} params.file The image file to upload
     * @returns {Promise<Icon>}
     * @throws {EneoError}
     */
    upload: async ({ file }) => {
      const formData = new FormData();
      formData.append("file", file);
      const res = await client.xhr(
        "/api/v1/icons/",
        {
          method: "post",
          //@ts-expect-error Typing for multipart/formdata upload does currently not work correctly
          requestBody: { "multipart/form-data": formData }
        },
        {}
      );
      return res;
    },

    /**
     * Delete an icon
     * @param {Object} params
     * @param {string} params.id The icon id to delete
     * @throws {EneoError}
     */
    delete: async ({ id }) => {
      await client.fetch(`/api/v1/icons/{id}/`, {
        method: "delete",
        params: { path: { id } }
      });
    },

    /**
     * Get the URL for an icon
     * @param {Object} params
     * @param {string} params.id The icon id
     * @returns {string}
     */
    url: ({ id }) => {
      return `${client.baseUrl.origin}/api/v1/icons/${id}/`;
    }
  };
}
