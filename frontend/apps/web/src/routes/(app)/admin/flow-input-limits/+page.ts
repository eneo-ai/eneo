export const load = async (event) => {
  const { intric } = await event.parent();
  const getFlowRuntimePolicy =
    intric.settings.getFlowRuntimePolicy ??
    (() =>
      intric.client.fetch("/api/v1/settings/flow-runtime-policy", {
        method: "get"
      }));
  const [flowInputLimits, flowRuntimePolicy] = await Promise.all([
    intric.settings.getFlowInputLimits(),
    getFlowRuntimePolicy()
  ]);
  return { flowInputLimits, flowRuntimePolicy };
};
