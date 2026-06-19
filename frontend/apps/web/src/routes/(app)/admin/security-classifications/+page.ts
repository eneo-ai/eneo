export const load = async (event) => {
  const { intric } = await event.parent();

  const [securityClassifications, flowClassificationRetentionPolicies] = await Promise.all([
    intric.securityClassifications.list(),
    intric.settings.listFlowClassificationRetentionPolicies()
  ]);

  return {
    securityClassifications,
    flowClassificationRetentionPolicies
  };
};
