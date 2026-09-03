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
  addProviderTitle: () => string;
  editProviderTitle: () => string;
  providerNamePlaceholder: () => string;
  /** Explains what the provider owns versus what Eneo controls. */
  providerManagedNote: () => string;
  forwardIdentityHint: () => string;
  noActiveProviderDescription: () => string;
  noProviders: () => string;
  /** Assistant-level toggle hint. */
  capabilityHint: () => string;
  /** Space-level toggle hint. */
  spaceHint: () => string;
  noActiveProviderHint: () => string;
  notAvailableHereHint: () => string;
};

export const CAPABILITIES: readonly CapabilityDescriptor[] = [
  {
    purpose: "web_search",
    icon: Globe,
    label: m.web_search,
    addProviderTitle: m.web_search_add_provider_title,
    editProviderTitle: m.web_search_edit_provider_title,
    providerNamePlaceholder: m.web_search_provider_name_placeholder,
    providerManagedNote: m.web_search_provider_managed_note,
    forwardIdentityHint: m.web_search_forward_identity_hint,
    noActiveProviderDescription: m.web_search_no_active_provider_description,
    noProviders: m.web_search_no_providers,
    capabilityHint: m.web_search_capability_hint,
    spaceHint: m.web_search_space_group_hint,
    noActiveProviderHint: m.web_search_no_active_provider_hint,
    notAvailableHereHint: m.web_search_not_available_here_hint
  },
  {
    purpose: "image_generation",
    icon: Image,
    label: m.image_generation,
    addProviderTitle: m.image_generation_add_provider_title,
    editProviderTitle: m.image_generation_edit_provider_title,
    providerNamePlaceholder: m.image_generation_provider_name_placeholder,
    providerManagedNote: m.image_generation_provider_managed_note,
    forwardIdentityHint: m.image_generation_forward_identity_hint,
    noActiveProviderDescription: m.image_generation_no_active_provider_description,
    noProviders: m.image_generation_no_providers,
    capabilityHint: m.image_generation_capability_hint,
    spaceHint: m.image_generation_space_group_hint,
    noActiveProviderHint: m.image_generation_no_active_provider_hint,
    notAvailableHereHint: m.image_generation_not_available_here_hint
  }
];

/** True for any non-general purpose, including ones this build does not know. */
export function isCapabilityPurpose(purpose: string | null | undefined): boolean {
  return !!purpose && purpose !== GENERAL_PURPOSE;
}

export function getCapability(
  purpose: string | null | undefined
): CapabilityDescriptor | undefined {
  return CAPABILITIES.find((capability) => capability.purpose === purpose);
}
