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
        max_files_per_run: res.max_files_per_run ?? null,
        audio_max_files_per_run: res.audio_max_files_per_run ?? null
      };
    },

    /**
     * Update flow input limit settings for the current tenant.
     * @param {Partial<import('../types/resources').FlowInputLimits>} patch
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
        max_files_per_run: res.max_files_per_run ?? null,
        audio_max_files_per_run: res.audio_max_files_per_run ?? null
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
     * Preview an exact tenant-admin Flow retention proposal without changing policy.
     * @param {import('../types/resources').FlowRetentionOrganizationPreviewRequest} proposal
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRetentionImpactPreview>}
     */
    previewFlowRetentionPolicy: async (proposal) => {
      return await client.fetch("/api/v1/settings/flow-retention-policy/preview", {
        method: "post",
        requestBody: { "application/json": proposal }
      });
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
     * List full run-history retention policies keyed by security classification.
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowClassificationRetentionPolicies>}
     */
    listFlowClassificationRetentionPolicies: async () => {
      const res = await client.fetch("/api/v1/settings/flow-classification-retention-policies", {
        method: "get"
      });
      return res;
    },

    /**
     * Preview an exact classification retention proposal without changing policy.
     * @param {string} securityClassificationId
     * @param {import('../types/resources').FlowClassificationRetentionPolicyPreviewRequest} proposal
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowRetentionImpactPreview>}
     */
    previewFlowClassificationRetentionPolicy: async (securityClassificationId, proposal) => {
      return await client.fetch(
        "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}/preview",
        {
          method: "post",
          params: {
            path: {
              security_classification_id: securityClassificationId
            }
          },
          requestBody: { "application/json": proposal }
        }
      );
    },

    /**
     * Replace the desired retention policy for one security classification.
     * @param {string} securityClassificationId
     * @param {import('../types/resources').FlowClassificationRetentionPolicyUpdate} payload
     * @throws {EneoError}
     * @returns {Promise<import('../types/resources').FlowClassificationRetentionPolicy | null>}
     */
    putFlowClassificationRetentionPolicy: async (securityClassificationId, payload) => {
      const res = await client.fetch(
        "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}",
        {
          method: "put",
          params: {
            path: {
              security_classification_id: securityClassificationId
            }
          },
          requestBody: { "application/json": payload }
        }
      );
      return res;
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
     * @param {Partial<import('../types/resources').AIBuilderBudgetSettings>} patch
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
