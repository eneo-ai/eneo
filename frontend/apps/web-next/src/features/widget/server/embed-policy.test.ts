import type { WidgetPublicConfig } from "@eneo/eneo-js";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  embedPolicy,
  frameAncestorsFor,
  originSource,
  parseEmbedPath,
  resetEmbedPolicyCache
} from "./embed-policy";

function config(overrides: Partial<WidgetPublicConfig> = {}): WidgetPublicConfig {
  return {
    public_id: "wgt_aaaaaaaaaaaaaaaaaaaaaa",
    name: "Kaffe",
    texts: { title: "Kaffe", subtitle: "AI-assistent", welcome: "", suggested_questions: [] },
    theme: { color_scheme: "auto", logo_url: null },
    language: "auto",
    frame_ancestors: ["https://www.sundsvall.se", "*.sundsvall.se"],
    ...overrides
  } as unknown as WidgetPublicConfig;
}

const embed = { publicId: "wgt_aaaaaaaaaaaaaaaaaaaaaa", pathLocale: "sv" as const };

afterEach(() => resetEmbedPolicyCache());

describe("parseEmbedPath", () => {
  it("recognises the Swedish and English embed paths and nothing else", () => {
    expect(parseEmbedPath("/embed/wgt_x")).toEqual({ publicId: "wgt_x", pathLocale: "sv" });
    expect(parseEmbedPath("/en/embed/wgt_x")).toEqual({ publicId: "wgt_x", pathLocale: "en" });
    expect(parseEmbedPath("/embed/wgt_x/more")).toBeNull();
    expect(parseEmbedPath("/embedded")).toBeNull();
    expect(parseEmbedPath("/login")).toBeNull();
  });
});

describe("frame sources", () => {
  it("keeps host sources and drops anything that could break the directive", () => {
    expect(frameAncestorsFor(["https://www.sundsvall.se", "*.sundsvall.se", "x y", ""])).toBe(
      "'self' https://www.sundsvall.se *.sundsvall.se"
    );
    expect(frameAncestorsFor([])).toBe("'none'");
    expect(originSource("https://cdn.example.org/logo.png?x=1")).toBe("https://cdn.example.org");
    expect(originSource("not a url")).toBeNull();
  });
});

describe("embedPolicy", () => {
  it("frames an active widget where its configuration allows, with its logo host", async () => {
    const fetchConfig = vi.fn(async () =>
      config({
        theme: { color_scheme: "dark", logo_url: "https://cdn.example.org/logo.png" },
        language: "en"
      } as Partial<WidgetPublicConfig>)
    );
    const policy = await embedPolicy(embed, new URLSearchParams("scheme=light"), { fetchConfig });
    expect(policy).toEqual({
      frameAncestors: "'self' https://www.sundsvall.se *.sundsvall.se",
      imgSources: ["https://cdn.example.org"],
      // Pinned settings win over the path and the host page.
      locale: "en",
      scheme: "dark"
    });
  });

  it("follows the path's language and the host's scheme when the widget is not pinned", async () => {
    const fetchConfig = vi.fn(async () => config());
    const policy = await embedPolicy(
      { ...embed, pathLocale: "en" },
      new URLSearchParams("scheme=dark"),
      { fetchConfig }
    );
    expect(policy.locale).toBe("en");
    expect(policy.scheme).toBe("dark");
    expect((await embedPolicy(embed, new URLSearchParams(), { fetchConfig })).scheme).toBe(
      "system"
    );
  });

  it("frames the stand-alone page and the preview only on Eneo itself", async () => {
    const fetchConfig = vi.fn(async () => config());
    expect(
      (await embedPolicy(embed, new URLSearchParams("mode=full"), { fetchConfig })).frameAncestors
    ).toBe("'self'");
    const preview = await embedPolicy(embed, new URLSearchParams("preview=1"), { fetchConfig });
    expect(preview.frameAncestors).toBe("'self'");
    // The preview has no configuration yet, so it accepts any https image.
    expect(preview.imgSources).toEqual(["https:"]);
    expect(fetchConfig).toHaveBeenCalledTimes(1);
  });

  it("lets any site frame the notice for a paused widget or a backend failure", async () => {
    expect(
      (await embedPolicy(embed, new URLSearchParams(), { fetchConfig: vi.fn(async () => null) }))
        .frameAncestors
    ).toBe("*");
    resetEmbedPolicyCache();
    expect(
      (
        await embedPolicy(embed, new URLSearchParams(), {
          fetchConfig: vi.fn(async () => {
            throw new Error("down");
          })
        })
      ).frameAncestors
    ).toBe("*");
  });

  it("reads the configuration once per half minute per widget", async () => {
    const fetchConfig = vi.fn(async () => config());
    await embedPolicy(embed, new URLSearchParams(), { fetchConfig, now: 0 });
    await embedPolicy(embed, new URLSearchParams(), { fetchConfig, now: 29_000 });
    expect(fetchConfig).toHaveBeenCalledTimes(1);
    await embedPolicy(embed, new URLSearchParams(), { fetchConfig, now: 31_000 });
    expect(fetchConfig).toHaveBeenCalledTimes(2);
  });
});
