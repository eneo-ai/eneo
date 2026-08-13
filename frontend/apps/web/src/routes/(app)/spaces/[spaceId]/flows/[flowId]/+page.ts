import { error } from "@sveltejs/kit";
import { hasPermission } from "$lib/core/hasPermission";

export const ssr = false;

export const load = async (event) => {
  const { eneo, currentSpace, user } = await event.parent();
  const flowId = event.params.flowId;

  if (!hasPermission(user)("flows_manage")) {
    throw error(403);
  }

  const [flow, security] = await Promise.all([
    eneo.flows.get({ id: flowId }),
    eneo.securityClassifications.list()
  ]);
  if (flow.space_id !== currentSpace.id) {
    throw error(404);
  }

  return {
    flow,
    securityClassifications: security.security_enabled ? security.security_classifications : []
  };
};
