import { m } from "$lib/paraglide/messages";
export function readinessMessage(reason: string | null | undefined): string {
  const labels: Record<string, () => string> = {
    permission: m.tools_readiness_permission,
    space_disabled: m.tools_readiness_space_disabled,
    model_missing: m.tools_readiness_model_missing,
    model_disabled: m.tools_readiness_model_disabled,
    model_deprecated: m.tools_readiness_model_deprecated,
    model_provider_inactive: m.tools_readiness_model_provider_inactive,
    no_approved_tools: m.tools_readiness_no_approved_tools,
    classification: m.tools_readiness_classification,
    no_active_provider: m.tools_readiness_no_active_provider
  };
  return reason ? (labels[reason] ?? m.tools_readiness_unknown)() : "";
}
