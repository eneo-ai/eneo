import { describe, expect, test } from "bun:test";
import { forecastView } from "../../src/tools/forecast/view";

describe("the forecast view", () => {
  test("is self-contained and fits the host's resource limit", async () => {
    const app = await forecastView();
    expect(app.uri).toMatch(/^ui:\/\/forecast\/forecast-[a-f0-9]{12}\.html$/);
    expect(Buffer.byteLength(app.html)).toBeLessThan(2 * 1024 * 1024);
    expect(app.ui).toEqual({ prefersBorder: true });
    expect(app.html).not.toMatch(/<(?:script|link)\b[^>]*(?:src|href)=["']https?:\/\//i);
  });
});
