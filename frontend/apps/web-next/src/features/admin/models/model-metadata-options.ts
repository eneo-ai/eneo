export const HOSTING_REGIONS = [
  "swe",
  "eu",
  "usa",
  "chn",
  "can",
  "gbr",
  "isr",
  "kor",
  "deu",
  "fra",
  "jpn"
] as const;
export type HostingRegion = (typeof HOSTING_REGIONS)[number];

export const EMBEDDING_FAMILIES = ["openai", "e5"] as const;
export type EmbeddingFamily = (typeof EMBEDDING_FAMILIES)[number];

export function isHostingRegion(value: string): value is HostingRegion {
  return HOSTING_REGIONS.some((region) => region === value);
}

export function isEmbeddingFamily(value: string): value is EmbeddingFamily {
  return EMBEDDING_FAMILIES.some((family) => family === value);
}

// Provider defaults seed the form; the administrator can choose another region.
const PROVIDER_HOSTING: Record<string, HostingRegion> = {
  openai: "usa",
  anthropic: "usa",
  gemini: "usa",
  google: "usa",
  cohere: "can",
  mistral: "fra",
  deepseek: "chn",
  ai21: "isr",
  friendliai: "kor",
  aleph_alpha: "deu",
  nscale: "gbr",
  zhipuai: "chn",
  moonshot: "chn",
  baidu: "chn",
  volcengine: "chn"
};

export function defaultModelHosting(providerType: string): HostingRegion {
  return PROVIDER_HOSTING[providerType] ?? "swe";
}
