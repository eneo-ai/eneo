export const load = async (event) => {
  const { eneo } = await event.parent();

  const [securityClassifications, flowClassificationRetentionPolicies] = await Promise.all([
    eneo.securityClassifications.list(),
    eneo.settings.listFlowClassificationRetentionPolicies()
  ]);

  return {
    securityClassifications,
    flowClassificationRetentionPolicies
  };
};
