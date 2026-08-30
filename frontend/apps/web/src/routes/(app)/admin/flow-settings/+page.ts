export const load = async (event) => {
  const { eneo } = await event.parent();
  const [
    flowRetentionPolicy,
    flowRunRetentionPolicy,
    flowRunRetentionReviewQueue,
    spaceTargets,
    flowInputLimits,
    flowRuntimePolicy,
    mappedExecutionPolicy,
    aiBuilderBudgetSettings,
    ragEvidencePolicy
  ] = await Promise.all([
    eneo.settings.getFlowRetentionPolicy(),
    eneo.settings.getOrganizationFlowRunRetentionPolicy(),
    eneo.settings.listOrganizationFlowRunRetentionReviewQueue().catch(() => null),
    eneo.settings.listFlowRunRetentionSpaceTargets({ limit: 200, offset: 0 }),
    eneo.settings.getFlowInputLimits(),
    eneo.settings.getFlowRuntimePolicy(),
    eneo.settings.getMappedExecutionPolicy(),
    eneo.settings.getAIBuilderBudgetSettings(),
    eneo.settings.getRagEvidencePolicy()
  ]);
  return {
    flowRetentionPolicy,
    flowRunRetentionPolicy,
    flowRunRetentionReviewQueue,
    spaceTargets,
    flowInputLimits,
    flowRuntimePolicy,
    mappedExecutionPolicy,
    aiBuilderBudgetSettings,
    ragEvidencePolicy
  };
};
