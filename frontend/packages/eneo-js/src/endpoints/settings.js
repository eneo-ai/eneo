/** @typedef {import('../client/client').EneoError} EneoError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initSettings(client) {
  return {
    /**
     * Get settings for the current tenant
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    get: async () => {
      const res = await client.fetch("/api/v1/settings/", {
        method: "get"
      });
      return res;
    },

    /**
     * Update user settings
     * @param {import('../types/resources').Settings} settings
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    update: async (settings) => {
      const res = await client.fetch("/api/v1/settings/", {
        method: "post",
        requestBody: { "application/json": settings }
      });
      return res;
    },

    /**
     * Update template feature setting for the tenant
     * @param {boolean} enabled Whether to enable templates
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    updateTemplates: async (enabled) => {
      const res = await client.fetch("/api/v1/settings/templates", {
        method: "patch",
        requestBody: { "application/json": { enabled } }
      });
      return res;
    },

    /**
     * Update audit logging feature setting for the tenant
     * @param {boolean} enabled Whether to enable audit logging
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    updateAuditLogging: async (enabled) => {
      const res = await client.fetch("/api/v1/settings/audit-logging", {
        method: "patch",
        requestBody: { "application/json": { enabled } }
      });
      return res;
    },

    /**
     * Update JIT provisioning setting for the tenant
     * @param {boolean} enabled Whether to enable JIT provisioning (auto-create users on SSO login)
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    updateProvisioning: async (enabled) => {
      const res = await client.fetch("/api/v1/settings/provisioning", {
        method: "patch",
        requestBody: { "application/json": { enabled } }
      });
      return res;
    },

    /**
     * Update API key expiry notifications setting for the tenant
     * @param {boolean} enabled Whether to enable API key expiry notifications
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').Settings>}
     */
    updateApiKeyExpiryNotifications: async (enabled) => {
      const res = await client.fetch("/api/v1/settings/api-key-expiry-notifications", {
        method: "patch",
        requestBody: { "application/json": { enabled } }
      });
      return res;
    },

    /**
     * Get the active execution block for an organisation Skill.
     * @param {{skillId: string}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').SkillExecutionBlockState>}
     */
    getSkillExecutionBlock: async ({ skillId }) => {
      return await client.fetch("/api/v1/settings/skills/{skill_id}/execution-block", {
        method: "get",
        params: { path: { skill_id: skillId } }
      });
    },

    /**
     * Block an organisation Skill from subsequent runtime composition.
     * @param {{skillId: string, reason: string}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').SkillExecutionBlockState>}
     */
    blockSkillExecution: async ({ skillId, reason }) => {
      return await client.fetch("/api/v1/settings/skills/{skill_id}/execution-block", {
        method: "post",
        params: { path: { skill_id: skillId } },
        requestBody: { "application/json": { reason } }
      });
    },

    /**
     * Release the exact execution block reviewed by the administrator.
     * @param {{skillId: string, expectedBlockId: string, reason: string}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').SkillExecutionBlockState>}
     */
    unblockSkillExecution: async ({ skillId, expectedBlockId, reason }) => {
      return await client.fetch("/api/v1/settings/skills/{skill_id}/execution-block/unblock", {
        method: "post",
        params: { path: { skill_id: skillId } },
        requestBody: {
          "application/json": {
            expected_block_id: expectedBlockId,
            reason
          }
        }
      });
    },

    /**
     * Get the tenant-owned Skill runtime policy and its editable bounds.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').SkillRuntimePolicy>}
     */
    getSkillRuntimePolicy: async () => {
      return await client.fetch("/api/v1/settings/skills/runtime-policy", {
        method: "get"
      });
    },

    /**
     * Replace the tenant-owned Skill runtime policy.
     * @param {import('../types/resources').SkillRuntimePolicyUpdate} policy
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').SkillRuntimePolicy>}
     */
    updateSkillRuntimePolicy: async (policy) => {
      return await client.fetch("/api/v1/settings/skills/runtime-policy", {
        method: "put",
        requestBody: {
          "application/json": {
            selective_activation_enabled: policy.selective_activation_enabled,
            max_attached_skills: policy.max_attached_skills,
            context_share_percent: policy.context_share_percent,
            max_activations_per_turn: policy.max_activations_per_turn
          }
        }
      });
    },

    /**
     * Reset the tenant-owned Skill runtime policy to platform defaults.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').SkillRuntimePolicy>}
     */
    resetSkillRuntimePolicy: async () => {
      return await client.fetch("/api/v1/settings/skills/runtime-policy/reset", {
        method: "post"
      });
    },

    /**
     * Project the current context-share allowance onto accessible models.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').SkillRuntimeModelProjections>}
     */
    getSkillRuntimeModelProjections: async () => {
      return await client.fetch("/api/v1/settings/skills/runtime-policy/model-projections", {
        method: "get"
      });
    },

    /**
     * Set whether model input/output prices are shown to regular users (org-wide).
     * @param {boolean} enabled Whether to show model pricing to users
     * @throws {EneoError}
     * @returns {Promise<{ show_model_pricing: boolean }>}
     */
    updateModelPricingVisibility: async (enabled) => {
      const res = await client.fetch("/api/v1/admin/settings/model-pricing-visibility", {
        method: "put",
        requestBody: { "application/json": { show_model_pricing: enabled } }
      });
      return res;
    }
  };
}
