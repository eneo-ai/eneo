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
     * Get flow input limit settings for the current tenant.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowInputLimits>}
     */
    getFlowInputLimits: async () => {
      const res = await client.fetch("/api/v1/settings/flow-input-limits", {
        method: "get"
      });
      return {
        ...res,
        max_files_per_run: res.max_files_per_run ?? null
      };
    },

    /**
     * Update flow input limit settings for the current tenant.
     * @param {import('../types/resources').FlowInputLimitsUpdate} patch
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowInputLimits>}
     */
    updateFlowInputLimits: async (patch) => {
      const res = await client.fetch("/api/v1/settings/flow-input-limits", {
        method: "patch",
        requestBody: { "application/json": patch }
      });
      return {
        ...res,
        max_files_per_run: res.max_files_per_run ?? null
      };
    },

    /**
     * Get flow runtime timeout policy for the current tenant.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRuntimePolicy>}
     */
    getFlowRuntimePolicy: async () => {
      const res = await client.fetch("/api/v1/settings/flow-runtime-policy", {
        method: "get"
      });
      return res;
    },

    /**
     * Update flow runtime timeout policy for the current tenant.
     * @param {import('../types/resources').FlowRuntimePolicyUpdate} patch
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRuntimePolicy>}
     */
    updateFlowRuntimePolicy: async (patch) => {
      const res = await client.fetch("/api/v1/settings/flow-runtime-policy", {
        method: "patch",
        requestBody: { "application/json": patch }
      });
      return res;
    },

    /**
     * Get mapped execution limits for the current tenant.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowMappedExecutionPolicy>}
     */
    getMappedExecutionPolicy: async () => {
      return await client.fetch("/api/v1/settings/flow-mapped-execution-policy", {
        method: "get"
      });
    },

    /**
     * Update mapped execution limits for the current tenant.
     * @param {import('../types/resources').FlowMappedExecutionPolicyUpdate} patch
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowMappedExecutionPolicy>}
     */
    updateMappedExecutionPolicy: async (patch) => {
      return await client.fetch("/api/v1/settings/flow-mapped-execution-policy", {
        method: "patch",
        requestBody: { "application/json": patch }
      });
    },

    /**
     * Get knowledge evidence recording limits for the current tenant.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRagEvidencePolicy>}
     */
    getRagEvidencePolicy: async () => {
      return await client.fetch("/api/v1/settings/flow-rag-evidence-policy", {
        method: "get"
      });
    },

    /**
     * Update knowledge evidence recording limits for the current tenant.
     * @param {import('../types/resources').FlowRagEvidencePolicyUpdate} patch
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRagEvidencePolicy>}
     */
    updateRagEvidencePolicy: async (patch) => {
      return await client.fetch("/api/v1/settings/flow-rag-evidence-policy", {
        method: "patch",
        requestBody: { "application/json": patch }
      });
    },

    /**
     * Get flow evidence export policy for the current tenant.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowEvidencePolicy>}
     */
    getFlowEvidencePolicy: async () => {
      const res = await client.fetch("/api/v1/settings/flow-evidence-policy", {
        method: "get"
      });
      return res;
    },

    /**
     * Update flow evidence export policy for the current tenant.
     * @param {Partial<import('../types/resources').FlowEvidencePolicy>} patch
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowEvidencePolicy>}
     */
    updateFlowEvidencePolicy: async (patch) => {
      const res = await client.fetch("/api/v1/settings/flow-evidence-policy", {
        method: "patch",
        requestBody: { "application/json": patch }
      });
      return res;
    },

    /**
     * Get the tenant-admin Flow retention control plane.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRetentionPolicy>}
     */
    getFlowRetentionPolicy: async () => {
      const res = await client.fetch("/api/v1/settings/flow-retention-policy", {
        method: "get"
      });
      return res;
    },

    /**
     * Update the tenant-admin Flow retention control plane.
     * @param {import('../types/resources').FlowRetentionPolicyUpdate} patch
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRetentionPolicy>}
     */
    updateFlowRetentionPolicy: async (patch) => {
      const res = await client.fetch("/api/v1/settings/flow-retention-policy", {
        method: "patch",
        requestBody: { "application/json": patch }
      });
      return res;
    },

    /**
     * Get the Organization default for Flow run-history retention.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionPolicySettings>}
     */
    getOrganizationFlowRunRetentionPolicy: async () => {
      return await client.fetch("/api/v1/settings/flow-run-retention-policy", {
        method: "get"
      });
    },

    /**
     * Replace or clear the Organization default for Flow run-history retention.
     * @param {{policy: import('../types/resources').FlowRunRetentionPolicy | null}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionPolicySettings>}
     */
    replaceOrganizationFlowRunRetentionPolicy: async ({ policy }) => {
      return await client.fetch("/api/v1/settings/flow-run-retention-policy", {
        method: "put",
        requestBody: { "application/json": { policy } }
      });
    },

    /**
     * List non-personal Spaces across the Organization for retention administration.
     * @param {{limit?: number, offset?: number}} [params]
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionSpaceTargetPage>}
     */
    listFlowRunRetentionSpaceTargets: async ({ limit = 200, offset = 0 } = {}) => {
      return await client.fetch("/api/v1/settings/flow-run-retention-policy/targets/spaces", {
        method: "get",
        params: { query: { limit, offset } }
      });
    },

    /**
     * List active Flows in a Space for Organization-wide retention administration.
     * @param {{spaceId: string, limit?: number, offset?: number}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionFlowTargetPage>}
     */
    listFlowRunRetentionFlowTargets: async ({ spaceId, limit = 200, offset = 0 }) => {
      return await client.fetch(
        "/api/v1/settings/flow-run-retention-policy/targets/spaces/{space_id}/flows",
        {
          method: "get",
          params: {
            path: { space_id: spaceId },
            query: { limit, offset }
          }
        }
      );
    },

    /**
     * Get one Space's local and effective Flow run-history retention policy.
     * @param {{spaceId: string}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionPolicySettings>}
     */
    getSpaceFlowRunRetentionPolicy: async ({ spaceId }) => {
      return await client.fetch("/api/v1/settings/flow-run-retention-policy/spaces/{space_id}", {
        method: "get",
        params: { path: { space_id: spaceId } }
      });
    },

    /**
     * Replace a Space override, or clear it to inherit the Organization default.
     * @param {{spaceId: string, policy: import('../types/resources').FlowRunRetentionPolicy | null}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionPolicySettings>}
     */
    replaceSpaceFlowRunRetentionPolicy: async ({ spaceId, policy }) => {
      return await client.fetch("/api/v1/settings/flow-run-retention-policy/spaces/{space_id}", {
        method: "put",
        params: { path: { space_id: spaceId } },
        requestBody: { "application/json": { policy } }
      });
    },

    /**
     * Get one Flow's local and effective run-history retention policy.
     * @param {{flowId: string}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionPolicySettings>}
     */
    getFlowRunRetentionPolicy: async ({ flowId }) => {
      return await client.fetch("/api/v1/settings/flow-run-retention-policy/flows/{flow_id}", {
        method: "get",
        params: { path: { flow_id: flowId } }
      });
    },

    /**
     * Replace a Flow override, or clear it to inherit its Space or Organization policy.
     * @param {{flowId: string, policy: import('../types/resources').FlowRunRetentionPolicy | null}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionPolicySettings>}
     */
    replaceFlowRunRetentionPolicy: async ({ flowId, policy }) => {
      return await client.fetch("/api/v1/settings/flow-run-retention-policy/flows/{flow_id}", {
        method: "put",
        params: { path: { flow_id: flowId } },
        requestBody: { "application/json": { policy } }
      });
    },

    /**
     * List Flow runs awaiting retention review across the Organization.
     * @param {{limit?: number, cursor?: string}} [params]
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionReviewPage>}
     */
    listOrganizationFlowRunRetentionReviewQueue: async ({ limit = 50, cursor } = {}) => {
      return await client.fetch("/api/v1/settings/flow-run-retention-policy/review-queue", {
        method: "get",
        params: { query: { limit, cursor } }
      });
    },

    /**
     * List Flow runs awaiting retention review in one Space.
     * @param {{spaceId: string, limit?: number, cursor?: string}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionReviewPage>}
     */
    listSpaceFlowRunRetentionReviewQueue: async ({ spaceId, limit = 50, cursor }) => {
      return await client.fetch(
        "/api/v1/settings/flow-run-retention-policy/spaces/{space_id}/review-queue",
        {
          method: "get",
          params: {
            path: { space_id: spaceId },
            query: { limit, cursor }
          }
        }
      );
    },

    /**
     * List runs awaiting retention review for one Flow.
     * @param {{flowId: string, limit?: number, cursor?: string}} params
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRunRetentionReviewPage>}
     */
    listFlowRunRetentionReviewQueue: async ({ flowId, limit = 50, cursor }) => {
      return await client.fetch(
        "/api/v1/settings/flow-run-retention-policy/flows/{flow_id}/review-queue",
        {
          method: "get",
          params: {
            path: { flow_id: flowId },
            query: { limit, cursor }
          }
        }
      );
    },

    /**
     * Get generated PDF/DOCX render limits for the current tenant.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowDocumentRenderLimits>}
     */
    getFlowDocumentRenderLimits: async () => {
      const res = await client.fetch("/api/v1/settings/flow-document-render-limits", {
        method: "get"
      });
      return res;
    },

    /**
     * Update generated PDF/DOCX render limits for the current tenant.
     * @param {Partial<import('../types/resources').FlowDocumentRenderLimits>} patch
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowDocumentRenderLimits>}
     */
    updateFlowDocumentRenderLimits: async (patch) => {
      const res = await client.fetch("/api/v1/settings/flow-document-render-limits", {
        method: "patch",
        requestBody: { "application/json": patch }
      });
      return res;
    },

    /**
     * Get AI Builder budget settings for the current tenant.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').AIBuilderBudgetSettings>}
     */
    getAIBuilderBudgetSettings: async () => {
      const res = await client.fetch("/api/v1/settings/ai-builder-budget", {
        method: "get"
      });
      return res;
    },

    /**
     * Update AI Builder budget settings for the current tenant.
     * @param {import('../types/resources').AIBuilderBudgetSettingsUpdate} patch
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').AIBuilderBudgetSettings>}
     */
    updateAIBuilderBudgetSettings: async (patch) => {
      const res = await client.fetch("/api/v1/settings/ai-builder-budget", {
        method: "patch",
        requestBody: { "application/json": patch }
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
