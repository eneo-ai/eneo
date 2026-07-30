export const load = async (event) => {
  const { eneo } = await event.parent();
  const getFlowRuntimePolicy =
    eneo.settings.getFlowRuntimePolicy ??
    (() =>
      eneo.client.fetch("/api/v1/settings/flow-runtime-policy", {
        method: "get"
      }));
  const [flowInputLimits, flowRuntimePolicy, mappedExecutionPolicy, aiBuilderBudgetSettings] =
    await Promise.all([
      eneo.settings.getFlowInputLimits(),
      getFlowRuntimePolicy(),
      eneo.settings.getMappedExecutionPolicy(),
      eneo.settings.getAIBuilderBudgetSettings()
    ]);
  return {
    flowInputLimits,
    flowRuntimePolicy,
    mappedExecutionPolicy,
    aiBuilderBudgetSettings
  };
};
