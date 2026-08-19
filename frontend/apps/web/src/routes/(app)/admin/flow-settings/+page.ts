export const load = async (event) => {
  const { eneo } = await event.parent();
  const [
    flowRetentionPolicy,
    flowInputLimits,
    flowRuntimePolicy,
    mappedExecutionPolicy,
    ragEvidencePolicy,
    securityClassifications,
    flowClassificationRetentionPolicies
  ] = await Promise.all([
    eneo.settings.getFlowRetentionPolicy(),
    eneo.settings.getFlowInputLimits(),
    eneo.settings.getFlowRuntimePolicy(),
    eneo.settings.getMappedExecutionPolicy(),
    eneo.settings.getRagEvidencePolicy(),
    eneo.securityClassifications.list(),
    eneo.settings.listFlowClassificationRetentionPolicies()
  ]);
  return {
    flowRetentionPolicy,
    flowInputLimits,
    flowRuntimePolicy,
    mappedExecutionPolicy,
    ragEvidencePolicy,
    securityClassifications,
    flowClassificationRetentionPolicies
  };
};
