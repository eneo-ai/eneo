import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/runtime", () => ({
  localizeHref: (path: string) => `/en${path}`
}));

import { load } from "./+page";

describe("legacy news URL", () => {
  it("redirects old bookmarks with their query and fragment to the localized news URL", () => {
    // The redirect only reads the URL from SvelteKit's load event.
    expect(() =>
      load({ url: new URL("https://eneo.test/en/whats-new?version=2.2.0#skills") } as Parameters<
        typeof load
      >[0])
    ).toThrow(expect.objectContaining({ status: 308, location: "/en/news?version=2.2.0#skills" }));
  });
});
