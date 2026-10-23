import { Calculator, ChartColumn, FilePlus, FileSearch, Globe, Image } from "lucide-react";
import type { Schema } from "@/lib/api/models";

export type Capability = Schema<"CapabilityAvailability">["purpose"];

export type CapabilityDescriptor = {
  purpose: Capability;
  icon: typeof Globe;
  /** Space-level toggle hint (message key). */
  spaceHint: string;
  /** Assistant-level toggle hint (message key). */
  assistantHint: string;
  /** What the bundled tool runtime's provider of this function does, shown before it is added. */
  bundledDescription?: string;
  /** One line for the configured source row: what the bundled provider does, nothing about how. */
  bundledSummary?: string;
  /** A short usage note for administrators, with a link to the docs instead of more settings. */
  guide?: { hint: string; label: string; url: string };
};

/**
 * One display and readiness owner for the tenant functions. Adding a function
 * means adding one entry here (plus its messages); every admin, space,
 * assistant and chat surface renders from this list.
 */
export const CAPABILITIES: readonly CapabilityDescriptor[] = [
  {
    purpose: "web_search",
    icon: Globe,
    spaceHint: "web_search_space_group_hint",
    assistantHint: "web_search_capability_hint"
  },
  {
    purpose: "image_generation",
    icon: Image,
    spaceHint: "image_generation_space_group_hint",
    assistantHint: "image_generation_capability_hint"
  },
  {
    purpose: "file_analysis",
    icon: FileSearch,
    spaceHint: "file_analysis_space_group_hint",
    assistantHint: "file_analysis_capability_hint",
    bundledDescription: "tools_builtin_file_analysis_description",
    bundledSummary: "tools_builtin_file_analysis_summary"
  },
  {
    purpose: "file_creation",
    icon: FilePlus,
    spaceHint: "file_creation_space_group_hint",
    assistantHint: "file_creation_capability_hint",
    bundledDescription: "tools_builtin_file_creation_description",
    bundledSummary: "tools_builtin_file_creation_summary",
    guide: {
      hint: "tools_templates_hint",
      label: "tools_templates_guide",
      url: "https://docs.eneo.ai/guides/capabilities#word-templates"
    }
  },
  {
    purpose: "charts",
    icon: ChartColumn,
    spaceHint: "charts_space_group_hint",
    assistantHint: "charts_capability_hint",
    bundledDescription: "tools_builtin_charts_description",
    bundledSummary: "tools_builtin_charts_summary"
  },
  {
    purpose: "compute",
    icon: Calculator,
    spaceHint: "compute_space_group_hint",
    assistantHint: "compute_capability_hint",
    bundledDescription: "tools_builtin_compute_description",
    bundledSummary: "tools_builtin_compute_summary"
  }
];

export function getCapability(
  purpose: string | null | undefined
): CapabilityDescriptor | undefined {
  return CAPABILITIES.find((capability) => capability.purpose === purpose);
}

export function toggleCapability(selected: Capability[], purpose: Capability): Capability[] {
  return selected.includes(purpose)
    ? selected.filter((item) => item !== purpose)
    : [...selected, purpose];
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

export function capabilityBlockReason({
  enabled,
  spaceEnabled,
  available,
  modelSupportsTools
}: {
  enabled: boolean;
  spaceEnabled: boolean;
  available: boolean;
  modelSupportsTools: boolean;
}): "space_disabled" | "model_no_tool_calling" | "no_active_provider" | null {
  if (enabled) return null;
  if (!spaceEnabled) return "space_disabled";
  if (!modelSupportsTools) return "model_no_tool_calling";
  if (!available) return "no_active_provider";
  return null;
}

export const READINESS_KEYS: Record<string, string> = {
  permission: "tools_readiness_permission",
  space_disabled: "tools_readiness_space_disabled",
  server_disabled: "tools_readiness_server_disabled",
  model_missing: "tools_readiness_model_missing",
  model_disabled: "tools_readiness_model_disabled",
  model_deprecated: "tools_readiness_model_deprecated",
  model_provider_inactive: "tools_readiness_model_provider_inactive",
  no_approved_tools: "tools_readiness_no_approved_tools",
  classification: "tools_readiness_classification",
  no_active_provider: "tools_readiness_no_active_provider",
  model_no_tool_calling: "tools_readiness_model_no_tool_calling"
};

export function readinessKey(reason: string | null | undefined) {
  return READINESS_KEYS[reason ?? ""] ?? "tools_readiness_unknown";
}
