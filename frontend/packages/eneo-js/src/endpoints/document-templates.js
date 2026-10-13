/**
 * The organisation's document templates: the Word files generated documents are rendered
 * into, with one default, and Eneo's built-in template to adapt (admin only).
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initDocumentTemplates(client) {
  return {
    /**
     * List the organisation's document templates.
     * @throws {EneoError}
     */
    list: async () => {
      const res = await client.fetch("/api/v1/document-templates/", { method: "get" });
      return res;
    },

    /**
     * The organisation's templates by name, for choosing one on an assistant (any user).
     * @throws {EneoError}
     */
    listAvailable: async () => {
      const res = await client.fetch("/api/v1/document-templates/available/", {
        method: "get"
      });
      return res;
    },

    /**
     * Upload a Word (.docx) template.
     * @param {Object} params
     * @param {File} params.file The .docx file
     * @param {string} params.name The template's name in the library
     * @param {boolean} [params.isDefault] Make it the organisation's default
     * @throws {EneoError}
     */
    upload: async ({ file, name, isDefault = false }) => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("name", name);
      formData.append("is_default", isDefault ? "true" : "false");
      const res = await client.fetch("/api/v1/document-templates/", {
        method: "post",
        //@ts-expect-error Typing for multipart/formdata upload does currently not work correctly
        requestBody: { "multipart/form-data": formData }
      });
      return res;
    },

    /**
     * Rename a template or make it the organisation's default.
     * @param {Object} params
     * @param {string} params.id
     * @param {{ name?: string; is_default?: boolean }} params.update
     * @throws {EneoError}
     */
    update: async ({ id, update }) => {
      const res = await client.fetch("/api/v1/document-templates/{id}/", {
        method: "patch",
        params: { path: { id } },
        requestBody: { "application/json": update }
      });
      return res;
    },

    /**
     * Replace a template's Word file; the template keeps its id.
     * @param {Object} params
     * @param {string} params.id
     * @param {File} params.file The new .docx file
     * @throws {EneoError}
     */
    replaceContent: async ({ id, file }) => {
      const formData = new FormData();
      formData.append("file", file);
      const res = await client.fetch("/api/v1/document-templates/{id}/content/", {
        method: "put",
        params: { path: { id } },
        //@ts-expect-error Typing for multipart/formdata upload does currently not work correctly
        requestBody: { "multipart/form-data": formData }
      });
      return res;
    },

    /**
     * Remove a template. Assistants that selected it fall back to the default.
     * @param {Object} params
     * @param {string} params.id
     * @throws {EneoError}
     */
    delete: async ({ id }) => {
      const res = await client.fetch("/api/v1/document-templates/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * A template's Word file (admin only).
     * @param {Object} params
     * @param {string} params.id
     * @returns {Promise<Blob>}
     * @throws {EneoError}
     */
    downloadContent: async ({ id }) => {
      // A GET download carries no body; the download helper's type still asks for the key.
      // @ts-expect-error requestBody is never for this route
      return await client.download("/api/v1/document-templates/{id}/content/", {
        method: "get",
        params: { path: { id } }
      });
    },

    /**
     * Eneo's built-in template, to adapt in Word (admin only).
     * @param {Object} [params]
     * @param {"sv" | "en"} [params.language]
     * @returns {Promise<Blob>}
     * @throws {EneoError}
     */
    downloadBuiltin: async ({ language = "sv" } = {}) => {
      // @ts-expect-error requestBody is never for this route
      return await client.download("/api/v1/document-templates/builtin/", {
        method: "get",
        params: { query: { language } }
      });
    }
  };
}
