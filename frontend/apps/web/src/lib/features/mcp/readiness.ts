import { m } from "$lib/paraglide/messages";
export function readinessMessage(reason: string | null | undefined): string {
  const labels: Record<string, () => string> = {
    permission: m.tools_readiness_permission,
    space_disabled: m.tools_readiness_space_disabled,
    server_disabled: m.tools_readiness_server_disabled,
    model_missing: m.tools_readiness_model_missing,
    model_disabled: m.tools_readiness_model_disabled,
    model_deprecated: m.tools_readiness_model_deprecated,
    model_provider_inactive: m.tools_readiness_model_provider_inactive,
    no_approved_tools: m.tools_readiness_no_approved_tools,
    classification: m.tools_readiness_classification,
    no_active_provider: m.tools_readiness_no_active_provider,
    model_no_tool_calling: m.tools_readiness_model_no_tool_calling
  };
  return reason ? (labels[reason] ?? m.tools_readiness_unknown)() : "";
}

/**
 * Whether the completion model can call tools at all. Mirrors the backend
 * gate (`if not model.supports_tool_calling`): only an explicit `true` lets
 * MCP servers, capabilities and loopback tools reach the model, so a missing
 * flag counts as no support rather than as unknown.
 */
export function modelSupportsToolCalling(
  model: { supports_tool_calling?: boolean | null } | null | undefined
): boolean {
  return model?.supports_tool_calling === true;
}
