/**
 * Capability purposes: MCP servers that act as the tenant's provider for one
 * capability (web search, image generation). The backend resolves an attached
 * capability marker to the active provider at ask time, so every surface here
 * treats them as on/off capabilities rather than as servers.
 *
 * Adding a capability means adding one entry here (plus its messages); every
 * admin, space, assistant and chat surface renders from this list.
 */
import { Globe, Image } from "lucide-svelte";
import { m } from "$lib/paraglide/messages";

export const GENERAL_PURPOSE = "general";

export type CapabilityPurpose = "web_search" | "image_generation";

export type CapabilityDescriptor = {
  purpose: CapabilityPurpose;
  icon: typeof Globe;
  /** Capability name as shown in toggles, tabs and the chat popover. */
  label: () => string;
  providerNamePlaceholder: () => string;
  /** Explains what the provider owns versus what Eneo controls. */
  providerManagedNote: () => string;
  forwardIdentityHint: () => string;
  /** Assistant-level toggle hint. */
  capabilityHint: () => string;
  /** Space-level toggle hint. */
  spaceHint: () => string;
  noActiveProviderHint: () => string;
  notAvailableHereHint: () => string;
  /** Space-level hint when no active provider meets the space's classification. */
  classificationHint: () => string;
  /** Eneo can serve this capability itself, through a catalog image model. */
  builtinProvider?: boolean;
};

export const CAPABILITIES: readonly CapabilityDescriptor[] = [
  {
    purpose: "web_search",
    icon: Globe,
    label: m.web_search,
    providerNamePlaceholder: m.web_search_provider_name_placeholder,
    providerManagedNote: m.web_search_provider_managed_note,
    forwardIdentityHint: m.web_search_forward_identity_hint,
    capabilityHint: m.web_search_capability_hint,
    spaceHint: m.web_search_space_group_hint,
    noActiveProviderHint: m.web_search_no_active_provider_hint,
    notAvailableHereHint: m.web_search_not_available_here_hint,
    classificationHint: m.web_search_classification_hint
  },
  {
    purpose: "image_generation",
    icon: Image,
    label: m.image_generation,
    providerNamePlaceholder: m.image_generation_provider_name_placeholder,
    providerManagedNote: m.image_generation_provider_managed_note,
    forwardIdentityHint: m.image_generation_forward_identity_hint,
    capabilityHint: m.image_generation_capability_hint,
    spaceHint: m.image_generation_space_group_hint,
    noActiveProviderHint: m.image_generation_no_active_provider_hint,
    notAvailableHereHint: m.image_generation_not_available_here_hint,
    classificationHint: m.image_generation_classification_hint,
    builtinProvider: true
  }
];

/** Whether Eneo offers a built-in provider (no external MCP server) for the purpose. */
export function hasBuiltinProvider(purpose: string | null | undefined): boolean {
  return getCapability(purpose)?.builtinProvider === true;
}

/**
 * Whether the signed-in user may USE a capability. The role permission value
 * equals the purpose string, so no per-capability lookup table is needed.
 * Configuring a capability on an assistant or space is not gated by this.
 */
export function canUseCapability(
  user: { hasPermission: (permission: CapabilityPurpose) => boolean },
  purpose: string | null | undefined
): boolean {
  if (!isCapabilityPurpose(purpose)) return true;
  return user.hasPermission(purpose as CapabilityPurpose);
}

/**
 * The providers of `purpose` a space may attach: any active provider when
 * the space is unclassified, otherwise only providers at or above the space's
 * classification. Unclassified providers never qualify for a classified space.
 */
export function qualifyingProviders<
  T extends { purpose?: string | null; security_classification?: { security_level: number } | null }
>(
  servers: T[],
  purpose: string,
  spaceClassification: { security_level: number } | null | undefined
): T[] {
  const providers = servers.filter((server) => server.purpose === purpose);
  if (!spaceClassification) return providers;
  return providers.filter(
    (server) =>
      !!server.security_classification &&
      server.security_classification.security_level >= spaceClassification.security_level
  );
}

/** True for any non-general purpose, including ones this build does not know. */
export function isCapabilityPurpose(purpose: string | null | undefined): boolean {
  return !!purpose && purpose !== GENERAL_PURPOSE;
}

export function getCapability(
  purpose: string | null | undefined
): CapabilityDescriptor | undefined {
  return CAPABILITIES.find((capability) => capability.purpose === purpose);
}
