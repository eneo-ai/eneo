import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));

import { offeredFavoriteTypes, type ModelProviderCapabilities } from "./modelProviderCapabilities";

const catalog = {
  providers: {
    openai: { modes: ["completion"], models: {}, fields: [] },
    bedrock: { modes: ["completion"], models: {}, fields: [] }
  },
  default_fields: []
} as unknown as ModelProviderCapabilities;

describe("favourite provider types", () => {
  it("hides a favourite whose type the catalog no longer offers", () => {
    expect(offeredFavoriteTypes(["bedrock_converse", "openai", "github_copilot"], catalog)).toEqual(
      ["openai"]
    );
  });

  it("keeps every favourite until a catalog has loaded", () => {
    const favorites = ["bedrock_converse", "openai"];

    expect(offeredFavoriteTypes(favorites, null)).toEqual(favorites);
    expect(
      offeredFavoriteTypes(favorites, {
        providers: {},
        default_fields: []
      } as unknown as ModelProviderCapabilities)
    ).toEqual(favorites);
  });
});
