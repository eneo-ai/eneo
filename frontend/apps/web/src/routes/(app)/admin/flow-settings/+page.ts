export const load = async (event) => {
  const { eneo } = await event.parent();
  const [
    flowRetentionPolicy,
    flowInputLimits,
    flowRuntimePolicy,
    mappedExecutionPolicy,
    aiBuilderBudgetSettings,
    ragEvidencePolicy
  ] = await Promise.all([
    eneo.settings.getFlowRetentionPolicy(),
    eneo.settings.getFlowInputLimits(),
    eneo.settings.getFlowRuntimePolicy(),
    eneo.settings.getMappedExecutionPolicy(),
    eneo.settings.getAIBuilderBudgetSettings(),
    eneo.settings.getRagEvidencePolicy()
  ]);
  return {
    flowRetentionPolicy,
    flowInputLimits,
    flowRuntimePolicy,
    mappedExecutionPolicy,
    aiBuilderBudgetSettings,
    ragEvidencePolicy
  };
};
