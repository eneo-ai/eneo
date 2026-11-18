// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";
import { renderInApp } from "@/test/render";
import {
  SaveStatusIndicator,
  SaveStatusProvider,
  useSetSaveStatus
} from "@/components/composites/save-status";
import type { McpServer } from "../mcp";
import { OverviewTab } from "./overview-tab";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const server = {
  id: "server",
  name: "Diariet",
  http_url: "https://remote.example/mcp",
  http_auth_type: "api_key_header",
  purpose: "general",
  tags: [],
  mcp_server_id: "server",
  description: null,
  has_credentials: true,
  icon_url: null,
  documentation_url: null,
  security_classification: null,
  is_org_enabled: true,
  tools_count: 0,
  is_available: true
} satisfies McpServer;
afterEach(() => vi.clearAllMocks());

function OtherFieldStatus({ status }: { status: "dirty" | "error" }) {
  const setStatus = useSetSaveStatus();
  useEffect(() => {
    setStatus?.("other-field", status);
    return () => setStatus?.("other-field", null);
  }, [setStatus, status]);
  return null;
}

describe("OverviewTab MCP settings", () => {
  it.each(["dirty", "error"] as const)(
    "keeps another field's %s status when discarding purpose",
    async (status) => {
      api.POST.mockResolvedValue({
        error: { message: "fixture refusal" },
        response: new Response("{}", { status: 400 })
      });
      renderInApp(
        <SaveStatusProvider>
          <SaveStatusIndicator />
          <OverviewTab server={server} />
          <OtherFieldStatus status={status} />
        </SaveStatusProvider>
      );
      fireEvent.change(screen.getByLabelText("Funktion"), { target: { value: "web_search" } });
      fireEvent.click(screen.getByRole("button", { name: "Spara" }));
      await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Avbryt" }).hasAttribute("disabled")).toBe(false)
      );
      fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
      const error = screen.queryByRole("link", { name: "Kunde inte spara ändringarna" });
      if (status === "error") expect(error?.getAttribute("href")).toBe("#other-field");
      else expect(error).toBeNull();
      const leaving = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(leaving);
      expect(leaving.defaultPrevented).toBe(true);
    }
  );

  it("saves a new purpose after a discarded failure without retaining its error", async () => {
    api.POST.mockResolvedValueOnce({
      error: { message: "fixture refusal" },
      response: new Response("{}", { status: 400 })
    }).mockResolvedValue({ data: server, response: new Response() });
    renderInApp(
      <SaveStatusProvider>
        <SaveStatusIndicator />
        <OverviewTab server={server} />
      </SaveStatusProvider>
    );
    fireEvent.change(screen.getByLabelText("Funktion"), { target: { value: "web_search" } });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await screen.findByRole("link", { name: "Kunde inte spara ändringarna" });
    fireEvent.change(screen.getByLabelText("Funktion"), { target: { value: "general" } });
    fireEvent.change(screen.getByLabelText("Funktion"), { target: { value: "image_generation" } });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Spara" })).toBeNull());
    expect(screen.queryByRole("link", { name: "Kunde inte spara ändringarna" })).toBeNull();
    expect(api.POST).toHaveBeenLastCalledWith("/api/v1/mcp-servers/{id}/", {
      params: { path: { id: "server" } },
      body: { purpose: "image_generation" }
    });
  });
  it.each(["cancel", "original"])(
    "clears a failed purpose save when discarded through %s",
    async (discard) => {
      api.POST.mockResolvedValue({
        error: { message: "fixture refusal" },
        response: new Response("{}", { status: 400 })
      });
      renderInApp(
        <SaveStatusProvider>
          <SaveStatusIndicator />
          <OverviewTab server={server} />
        </SaveStatusProvider>
      );
      fireEvent.change(screen.getByLabelText("Funktion"), { target: { value: "web_search" } });
      fireEvent.click(screen.getByRole("button", { name: "Spara" }));
      await screen.findByRole("link", { name: "Kunde inte spara ändringarna" });
      if (discard === "cancel") fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
      else fireEvent.change(screen.getByLabelText("Funktion"), { target: { value: "general" } });
      expect(screen.queryByRole("link", { name: "Kunde inte spara ändringarna" })).toBeNull();
      const leaving = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(leaving);
      expect(leaving.defaultPrevented).toBe(false);
    }
  );
  it("refuses credentialed URL edits over remote HTTP before autosaving", async () => {
    renderInApp(<OverviewTab server={server} />);
    const url = screen.getByLabelText("URL");
    fireEvent.change(url, { target: { value: "http://remote.example/mcp" } });
    fireEvent.blur(url);
    expect(url.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText(/Inloggningsuppgifter.*skickas bara över https/)).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("saves identity forwarding and bounded catalog limits without resending credentials", async () => {
    api.POST.mockResolvedValue({ data: server, response: new Response() });
    renderInApp(<OverviewTab server={server} />);
    fireEvent.click(screen.getByRole("switch", { name: "Vidarebefordra användaridentitet" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/", {
        params: { path: { id: "server" } },
        body: { forward_identity: true }
      })
    );
    const limit = screen.getByLabelText("Maximal katalogstorlek (MiB)");
    fireEvent.change(limit, { target: { value: "65" } });
    fireEvent.blur(limit);
    expect(limit.getAttribute("aria-invalid")).toBe("true");
    expect(api.POST).toHaveBeenCalledTimes(1);
    fireEvent.change(limit, { target: { value: "32" } });
    fireEvent.blur(limit);
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/", {
        params: { path: { id: "server" } },
        body: { tool_catalog_max_bytes: 32 * 1048576 }
      })
    );
  });

  it("explains promotion before saving only the purpose, leaving activation explicit", async () => {
    api.POST.mockResolvedValue({ data: server, response: new Response() });
    const { queryClient } = renderInApp(<OverviewTab server={server} />);
    queryClient.setQueryData(["spaces"], []);
    fireEvent.change(screen.getByLabelText("Funktion"), { target: { value: "web_search" } });
    expect(screen.getByText(/inaktiv tills du aktiverar/)).toBeTruthy();
    expect(api.POST).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/", {
        params: { path: { id: "server" } },
        body: { purpose: "web_search" }
      })
    );
  });

  it.each(["internal", "bundled"])("keeps %s connection and purpose managed", (auth) => {
    renderInApp(
      <OverviewTab server={{ ...server, http_auth_type: auth, purpose: "image_generation" }} />
    );
    expect(screen.queryByLabelText("Funktion")).toBeNull();
    expect(screen.queryByLabelText("URL")).toBeNull();
    expect(screen.queryByRole("switch", { name: "Vidarebefordra användaridentitet" })).toBeNull();
  });
});
