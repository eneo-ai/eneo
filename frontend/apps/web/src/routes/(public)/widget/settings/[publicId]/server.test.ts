/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { describe, expect, test, vi } from "vitest";
import { EneoError, type WidgetPublicConfig } from "@eneo/eneo-js";
import { parseWidgetSettings } from "../../../../../../../../packages/widget-loader/src/protocol";

const backend = vi.hoisted(() => ({
  config: (async () => ({})) as () => Promise<unknown>,
  publicIds: [] as string[]
}));

vi.mock("$lib/core/environment.server", () => ({ getBackendUrl: () => "http://backend" }));
vi.mock("@eneo/eneo-js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@eneo/eneo-js")>();
  return {
    ...actual,
    createWidgetClient: ({ publicId }: { publicId: string }) => {
      backend.publicIds.push(publicId);
      return { config: () => backend.config() };
    }
  };
});

import { GET } from "./+server";

function config(theme: Partial<WidgetPublicConfig["theme"]>, language = "en"): WidgetPublicConfig {
  return { public_id: "wgt_x", name: "Chatten", theme, language } as WidgetPublicConfig;
}

const request = () => GET({ params: { publicId: "wgt_x" }, fetch } as never);

describe("GET /widget/settings/[publicId]", () => {
  test("answers any host page with the saved language, position and colours", async () => {
    backend.config = async () =>
      config({ position: "bottom-left", primary_color: "#1F4E79", primary_color_dark: "#9CC7F0" });

    const response = await request();

    expect(response.status).toBe(200);
    expect(response.headers.get("access-control-allow-origin")).toBe("*");
    expect(response.headers.get("cache-control")).toBe("public, max-age=60");
    expect(backend.publicIds.at(-1)).toBe("wgt_x");
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

    const body = await (await request()).json();

    expect(body.position).toBe("bottom-right");
    expect(body.language).toBe("auto");
    expect(parseWidgetSettings(body)?.language).toBeNull();
  });

  test("answers 404 without caching for a paused, draft or unknown widget", async () => {
    backend.config = async () => {
      throw new EneoError("Not found", "SERVER", 404, 0);
    };

    const response = await request();

    expect(response.status).toBe(404);
    expect(response.headers.get("access-control-allow-origin")).toBe("*");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
});
