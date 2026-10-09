/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { afterEach, describe, expect, test, vi } from "vitest";
import { EneoError, type WidgetPublicConfig } from "@eneo/eneo-js";
import { parseWidgetSettings } from "../../../../../../../../packages/widget-loader/src/protocol";

const backend = vi.hoisted(() => ({
  config: (async () => ({})) as (fetch: typeof globalThis.fetch) => Promise<unknown>,
  publicIds: [] as string[]
}));

vi.mock("$lib/core/environment.server", () => ({ getBackendUrl: () => "http://backend" }));
vi.mock("@eneo/eneo-js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@eneo/eneo-js")>();
  return {
    ...actual,
    createWidgetClient: ({
      publicId,
      fetch
    }: {
      publicId: string;
      fetch: typeof globalThis.fetch;
    }) => ({
      config: () => {
        backend.publicIds.push(publicId);
        return backend.config(fetch);
      }
    })
  };
});

import { GET } from "./+server";

function config(theme: Partial<WidgetPublicConfig["theme"]>, language = "en"): WidgetPublicConfig {
  return { public_id: "wgt_x", name: "Chatten", theme, language } as WidgetPublicConfig;
}

const request = (publicId: string, fetch: typeof globalThis.fetch = globalThis.fetch) =>
  GET({ params: { publicId }, fetch } as never);

const asked = (publicId: string) => backend.publicIds.filter((id) => id === publicId).length;

/** A backend that never answers; the request fails only once it is aborted. */
const hangingFetch: typeof globalThis.fetch = (_input, init) =>
  new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () =>
      reject(new DOMException("aborted", "AbortError"))
    );
  });

afterEach(() => {
  vi.useRealTimers();
});

describe("GET /widget/settings/[publicId]", () => {
  test("answers any host page with the saved language, position and colours", async () => {
    backend.config = async () =>
      config({ position: "bottom-left", primary_color: "#1F4E79", primary_color_dark: "#9CC7F0" });

    const response = await request("wgt_saved");

    expect(response.status).toBe(200);
    expect(response.headers.get("access-control-allow-origin")).toBe("*");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(backend.publicIds.at(-1)).toBe("wgt_saved");
    const body = await response.json();
    expect(body).toEqual({
      language: "en",
      position: "bottom-left",
      colors: {
        light: { accent: "#1F4E79", on_accent: "#FFFFFF" },
        dark: { accent: "#9CC7F0", on_accent: "#111111" }
      }
    });
    // The loader reads every field it is sent; a rename on either side fails here.
    expect(parseWidgetSettings(body)).toEqual(body);
  });

  test("places a widget without a saved position bottom right and leaves auto to the host", async () => {
    backend.config = async () => config({}, "auto");

    const body = await (await request("wgt_auto")).json();

    expect(body.position).toBe("bottom-right");
    expect(body.language).toBe("auto");
    expect(parseWidgetSettings(body)?.language).toBeNull();
  });

  test("answers 404, kept by no browser, for a paused, draft or unknown widget", async () => {
    backend.config = async () => {
      throw new EneoError("Not found", "SERVER", 404, 0);
    };

    const response = await request("wgt_unknown");

    expect(response.status).toBe(404);
    expect(response.headers.get("access-control-allow-origin")).toBe("*");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  test("a new page view sees a pause and a resume without stale settings", async () => {
    backend.config = async () => config({ primary_color: "#1F4E79" });
    expect((await request("wgt_lifecycle")).status).toBe(200);

    backend.config = async () => {
      throw new EneoError("Not found", "SERVER", 404, 0);
    };
    expect((await request("wgt_lifecycle")).status).toBe(404);

    backend.config = async () => config({ position: "bottom-left" });
    const resumed = await request("wgt_lifecycle");
    expect(resumed.status).toBe(200);
    expect((await resumed.json()).position).toBe("bottom-left");
    expect(asked("wgt_lifecycle")).toBe(3);
  });

  test("answers a slow backend before the loader stops waiting after 3 s", async () => {
    vi.useFakeTimers();
    backend.config = (fetch) => fetch("http://backend/api/v1/widgets/wgt_slow/config/");

    const pending = request("wgt_slow", hangingFetch);
    await vi.advanceTimersByTimeAsync(2_500);
    const response = await pending;

    expect(response.status).toBe(503);
    expect(response.headers.get("access-control-allow-origin")).toBe("*");
    expect(response.headers.get("cache-control")).toBe("no-store");

    // A backend that never answers is aborted, and the next page view asks again.
    backend.config = async () => config({});
    expect((await request("wgt_slow")).status).toBe(200);
    expect(asked("wgt_slow")).toBe(2);
  });
});
