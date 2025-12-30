/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @typedef {Object} ImageModel
 * @property {string} id
 * @property {string} name
 * @property {string} nickname
 * @property {string} family
 * @property {boolean} is_deprecated
 * @property {string} stability
 * @property {string} hosting
 * @property {boolean} [open_source]
 * @property {string} [description]
 * @property {string} [hf_link]
 * @property {string} [org]
 * @property {boolean} can_access
 * @property {boolean} is_locked
 * @property {string} [lock_reason]
 * @property {boolean} is_org_enabled
 * @property {boolean} is_org_default
 * @property {string} [credential_provider]
 * @property {Object} [security_classification]
 * @property {string} [max_resolution]
 * @property {string[]} supported_sizes
 * @property {string[]} supported_qualities
 * @property {number} max_images_per_request
 */

/**
 * @typedef {Object} ImageVariant
 * @property {number} index
 * @property {string} blob_base64
 * @property {string} mimetype
 * @property {string} [revised_prompt]
 */

/**
 * @typedef {Object} IconGenerationResponse
 * @property {string} generated_prompt
 * @property {ImageVariant[]} variants
 */

/**
 * @typedef {Object} PromptPreviewResponse
 * @property {string} prompt
 */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initImageModels(client) {
  return {
    /**
     * List all image models with tenant-specific settings
     * @returns {Promise<{items: ImageModel[]}>}
     * @throws {IntricError}
     */
    list: async () => {
      const res = await client.fetch("/api/v1/image-models/", {
        method: "get"
      });
      return res;
    },

    /**
     * Update tenant-specific settings for an image model (admin only)
     * @param {Object} params
     * @param {{id: string}} params.imageModel The image model to update
     * @param {Object} params.update The update payload
     * @param {boolean} [params.update.is_org_enabled]
     * @param {boolean} [params.update.is_org_default]
     * @param {{id: string} | null} [params.update.security_classification]
     * @returns {Promise<ImageModel>}
     * @throws {IntricError}
     */
    update: async ({ imageModel, update }) => {
      const { id } = imageModel;
      const res = await client.fetch("/api/v1/image-models/{id}/", {
        method: "post",
        params: { path: { id } },
        requestBody: { "application/json": update }
      });
      return res;
    },

    /**
     * Generate icon variants for a resource
     * @param {Object} params
     * @param {string} params.resource_name The name of the resource
     * @param {string} [params.resource_description] Description of the resource
     * @param {string} [params.system_prompt] System prompt if applicable
     * @param {string} [params.custom_prompt] Custom prompt to use instead of auto-generated
     * @param {number} [params.num_variants] Number of variants to generate (1-4)
     * @param {string} [params.model_id] Specific image model to use
     * @returns {Promise<IconGenerationResponse>}
     * @throws {IntricError}
     */
    generateIconVariants: async ({
      resource_name,
      resource_description,
      system_prompt,
      custom_prompt,
      num_variants,
      model_id
    }) => {
      const res = await client.fetch("/api/v1/image-models/generate-icon-variants", {
        method: "post",
        requestBody: {
          "application/json": {
            resource_name,
            resource_description,
            system_prompt,
            custom_prompt,
            num_variants,
            model_id
          }
        }
      });
      return res;
    },

    /**
     * Preview the auto-generated prompt without generating images
     * @param {Object} params
     * @param {string} params.resource_name The name of the resource
     * @param {string} [params.resource_description] Description of the resource
     * @param {string} [params.system_prompt] System prompt if applicable
     * @returns {Promise<PromptPreviewResponse>}
     * @throws {IntricError}
     */
    previewPrompt: async ({ resource_name, resource_description, system_prompt }) => {
      const res = await client.fetch("/api/v1/image-models/preview-prompt", {
        method: "post",
        requestBody: {
          "application/json": {
            resource_name,
            resource_description,
            system_prompt
          }
        }
      });
      return res;
    }
  };
}
