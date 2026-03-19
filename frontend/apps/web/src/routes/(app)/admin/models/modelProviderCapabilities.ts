import type { Intric } from "@intric/intric-js";

export interface ModelProviderFieldDef {
  name: string;
  required: boolean;
  secret: boolean;
  in: "credentials" | "config";
}

export type CapabilityModel = string | { name?: string; [key: string]: unknown };

export interface ModelProviderCapability {
  modes: string[];
  models: Record<string, CapabilityModel[]>;
  fields: ModelProviderFieldDef[];
}

export interface ModelProviderCapabilities {
  providers: Record<string, ModelProviderCapability>;
  default_fields: ModelProviderFieldDef[];
}

let capabilitiesCache: ModelProviderCapabilities | null = null;
let capabilitiesPromise: Promise<ModelProviderCapabilities> | null = null;

export async function getModelProviderCapabilities(
  intric: Intric
): Promise<ModelProviderCapabilities> {
  if (capabilitiesCache) {
    return capabilitiesCache;
  }

  if (!capabilitiesPromise) {
    capabilitiesPromise = intric.modelProviders
      .getCapabilities()
      .then((capabilities) => {
        capabilitiesCache = capabilities as ModelProviderCapabilities;
        return capabilitiesCache;
      })
      .catch((error) => {
        capabilitiesPromise = null;
        throw error;
      });
  }

  return capabilitiesPromise;
}
