import { hasPermission } from "$lib/core/hasPermission.js";
import { hasRetentionPermission, retentionAccess } from "$lib/features/flows/retentionAccess";

// Each request matches what the user may read: the admin settings need admin,
// retention needs retention_manage or retention_holds, holds need
// retention_holds and the review queue retention_manage. The server checks
// every one of them again.
export const load = async (event) => {
  const { eneo, user } = await event.parent();
  const access = retentionAccess(hasPermission(user));
  const retention = hasRetentionPermission(access);
  const [
    flowRetentionPolicy,
    flowRunRetentionPolicy,
    flowRunRetentionReviewQueue,
    spaceTargets,
    flowRetentionHolds,
    holdReviewLimit,
    flowInputLimits,
    flowRuntimePolicy,
    mappedExecutionPolicy,
    aiBuilderBudgetSettings,
    ragEvidencePolicy
  ] = await Promise.all([
    access.admin ? eneo.settings.getFlowRetentionPolicy() : null,
    retention ? eneo.settings.getOrganizationFlowRunRetentionPolicy() : null,
    access.retentionManage
      ? eneo.settings.listOrganizationFlowRunRetentionReviewQueue().catch(() => null)
      : null,
    retention ? eneo.settings.listFlowRunRetentionSpaceTargets({ limit: 200, offset: 0 }) : null,
    access.retentionHolds
      ? eneo.settings.listFlowRetentionHolds({ limit: 200 }).catch(() => null)
      : null,
    retention ? eneo.settings.getFlowRetentionHoldReviewLimit().catch(() => null) : null,
    access.admin ? eneo.settings.getFlowInputLimits() : null,
    access.admin ? eneo.settings.getFlowRuntimePolicy() : null,
    access.admin ? eneo.settings.getMappedExecutionPolicy() : null,
    access.admin ? eneo.settings.getAIBuilderBudgetSettings() : null,
    access.admin ? eneo.settings.getRagEvidencePolicy() : null
  ]);
  return {
    access,
    flowRetentionPolicy,
    flowRunRetentionPolicy,
    flowRunRetentionReviewQueue,
    spaceTargets,
    flowRetentionHolds,
    holdReviewLimit,
    flowInputLimits,
    flowRuntimePolicy,
    mappedExecutionPolicy,
    aiBuilderBudgetSettings,
    ragEvidencePolicy
  };
};
