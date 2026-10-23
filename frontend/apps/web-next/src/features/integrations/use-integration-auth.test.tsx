// @vitest-environment jsdom
import { act, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { renderHookInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { useIntegrationAuth } from "./use-integration-auth";

const integration = {
  id: "ui-1",
  tenant_integration_id: "ti-1",
  integration_type: "sharepoint"
} as unknown as Schema<"UserIntegration">;

function popup() {
  return { location: { href: "about:blank" }, closed: false, close: vi.fn() };
}

afterEach(() => {
  cleanup();
  api.GET.mockReset();
  vi.restoreAllMocks();
});

describe("useIntegrationAuth", () => {
  it("points the popup at an https sign-in page", async () => {
    const opened = popup();
    vi.spyOn(window, "open").mockReturnValue(opened as unknown as Window);
    api.GET.mockResolvedValue({
      data: { auth_url: "https://login.microsoftonline.com/x/authorize?a=1", state: "s" },
      response: new Response(null, { status: 200 })
    });
    const onConnected = vi.fn();
    const { result } = renderHookInApp(() => useIntegrationAuth(onConnected));

    await act(() => result.current.connect(integration));

    expect(opened.location.href).toBe("https://login.microsoftonline.com/x/authorize?a=1");
    expect(onConnected).not.toHaveBeenCalled();
  });

  it.each(["http://login.example.com/", "javascript:alert(1)", "/relative"])(
    "refuses %j and closes the popup",
    async (auth_url) => {
      const opened = popup();
      vi.spyOn(window, "open").mockReturnValue(opened as unknown as Window);
      api.GET.mockResolvedValue({
        data: { auth_url, state: "s" },
        response: new Response(null, { status: 200 })
      });
      const onConnected = vi.fn();
      const { result } = renderHookInApp(() => useIntegrationAuth(onConnected));

      await act(() => result.current.connect(integration));

      expect(opened.location.href).toBe("about:blank");
      expect(opened.close).toHaveBeenCalled();
      expect(onConnected).toHaveBeenCalledWith(expect.objectContaining({ success: false }));
    }
  );
});
