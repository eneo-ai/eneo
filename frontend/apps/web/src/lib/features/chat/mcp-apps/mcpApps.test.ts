import { describe, expect, it, vi } from "vitest";
vi.mock("$lib/paraglide/messages", () => ({
  m: new Proxy({}, { get: (_target, key) => () => String(key) })
}));
import { appViewCalls, appViewTitle, isChartDocumentAsset } from "./mcpApps";

const chart = {
  tool_call_id: "chart-call",
  tool_name: "create_chart",
  is_bundled: true,
  app_view: { view_id: "chart-view", ui: {} }
};
describe("chart result presentation", () => {
  it("keeps document-only chart exports available without an inline view", () => {
    const asset = { ...chart, arguments: { display: "none" } };
    expect(isChartDocumentAsset(asset)).toBe(true);
    expect(appViewCalls([asset])).toEqual([]);
    expect(isChartDocumentAsset({ ...asset, is_bundled: false })).toBe(false);
    expect(isChartDocumentAsset(chart)).toBe(false);
    expect(appViewCalls([{ ...asset, is_bundled: false }])).toHaveLength(1);
  });
  it("shows the interactive app by default and hides it for explicit image exports", () => {
    expect(appViewCalls([chart])).toHaveLength(1);
    expect(appViewCalls([{ ...chart, arguments: { format: "auto" } }])).toHaveLength(1);
    expect(appViewCalls([{ ...chart, arguments: { format: "png" } }])).toEqual([]);
    expect(appViewCalls([{ ...chart, arguments: { include_svg: true } }])).toEqual([]);
  });
  it("does not apply bundled chart rules to an external tool with the same name", () => {
    const calls = appViewCalls([
      { ...chart, is_bundled: false, title: "External chart", arguments: { format: "png" } }
    ]);
    expect(calls).toHaveLength(1);
    expect(appViewTitle(calls[0])).toBe("External chart");
  });
  it("uses the localized title for the bundled chart", () => {
    expect(appViewTitle(appViewCalls([chart])[0])).toBe("mcp_app_chart_title");
  });
});
