import { beforeEach, describe, expect, test, vi } from "vitest";
import type { WidgetPublicConfig } from "@eneo/eneo-js";

const backend = vi.hoisted(() => ({ language: "auto" as string, failure: null as unknown }));

vi.mock("$lib/core/environment.server", () => ({ getBackendUrl: () => "http://backend" }));
vi.mock("@eneo/eneo-js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@eneo/eneo-js")>();
  return {
    ...actual,
    createWidgetClient: () => ({
      config: async () => {
        if (backend.failure) throw backend.failure;
        return {
          public_id: "wgt_x",
          name: "Chatten",
          theme: {},
          language: backend.language,
          frame_ancestors: ["https://www.kommun.se"]
        } as unknown as WidgetPublicConfig;
      }
    })
  };
});

import { EneoError } from "@eneo/eneo-js";
import { load } from "./+page.server";

const QUERY = "?origin=https%3A%2F%2Fwww.kommun.se&scheme=light";

function event(path: string) {
  const locals: Record<string, unknown> = {};
  return {
    input: {
      params: { publicId: "wgt_x" },
      url: new URL(`https://eneo.kommun.se${path}`),
      fetch,
      locals,
      setHeaders: () => {}
    } as never,
    locals
  };
}

describe("embed page load", () => {
  beforeEach(() => {
    backend.failure = null;
  });

  test("sends a host page that asked in Swedish to the widget's fixed English", async () => {
    backend.language = "en";
    const { input, locals } = event(`/embed/wgt_x${QUERY}`);

    await expect(load(input)).rejects.toMatchObject({
      status: 307,
      location: `/en/embed/wgt_x${QUERY}`
    });
    // The redirect itself may be framed by the same sites as the page.
    expect(locals.frameAncestors).toContain("https://www.kommun.se");
  });

  test("serves a widget that follows the host page in the language asked for", async () => {
    backend.language = "auto";
    const { input } = event(`/en/embed/wgt_x${QUERY}`);

    const data = (await load(input)) as { config: WidgetPublicConfig | null };

    expect(data.config?.language).toBe("auto");
  });

  test("serves a widget already in its fixed language", async () => {
    backend.language = "en";
    const { input } = event(`/en/embed/wgt_x${QUERY}`);

    const data = (await load(input)) as { config: WidgetPublicConfig | null };

    expect(data.config?.public_id).toBe("wgt_x");
  });

  test.each([
    ["a backend error", new EneoError("Bad gateway", "SERVER", 502, 0)],
    ["a timeout", new EneoError("fetch failed", "CONNECTION", 0, 0)]
  ])("lets any host frame the error page after %s", async (_case, failure) => {
    backend.failure = failure;
    const { input, locals } = event(`/embed/wgt_x${QUERY}`);

    await expect(load(input)).rejects.toBe(failure);
    // Refused, the frame would stay blank on the host site until it reloads.
    expect(locals.frameAncestors).toBe("*");
  });
});
