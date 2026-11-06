// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import type { McpServer } from "../mcp/mcp";
import { CapabilitySourceDialog } from "./capability-source-dialog";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const ok = (data: unknown) => Promise.resolve({ data, response: new Response() });
const model = {
  id: "image",
  name: "gpt-image",
  nickname: "Bilder",
  provider_id: "provider",
  provider_name: "Provider",
  is_org_enabled: true,
  is_deprecated: false,
  default_size: "1536x1024",
  default_quality: "high",
  security_classification: { id: "classification", name: "Intern" }
};
const server = {
  id: "source",
  mcp_server_id: "source",
  name: "Bildkälla",
  description: "",
  http_url: "http://backend/internal-mcp/image_generation/mcp",
  http_auth_type: "internal",
  purpose: "image_generation",
  image_model_id: "image",
  audience: "everyone",
  audience_priority: 100,
  has_credentials: false,
  tags: null,
  icon_url: null,
  documentation_url: null,
  security_classification: null,
  is_org_enabled: true,
  is_available: false,
  tools_count: 0,
  readiness_reason: "model_disabled"
} satisfies McpServer;
beforeEach(() => {
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/security-classifications/")
      return ok({
        security_enabled: true,
        security_classifications: [{ id: "classification", name: "Intern" }]
      });
    if (path === "/api/v1/admin/model-providers/")
      return ok([{ id: "provider", name: "Provider", provider_type: "openai", is_active: true }]);
    if (path === "/api/v1/admin/model-providers/capabilities/")
      return ok({
        providers: { openai: { modes: ["image"], models: {}, fields: [] } },
        default_fields: []
      });
    if (path === "/api/v1/image-models/") return ok({ items: [model] });
    if (path === "/api/v1/admin/model-providers/outbound-headers/options/")
      return ok({ supported_provider_types: [], dynamic_values: [], max_headers: 10 });
    return ok({ items: [], providers: [] });
  });
});
afterEach(() => vi.clearAllMocks());

describe("image function source configuration", () => {
  it("uses a loaded unclassified replacement without inheriting the saved model's classification", async () => {
    const previousGet = api.GET.getMockImplementation();
    api.GET.mockImplementation((path: string) =>
      path === "/api/v1/image-models/"
        ? ok({
            items: [
              model,
              {
                ...model,
                id: "unclassified",
                nickname: "Public model",
                security_classification: null
              }
            ]
          })
        : previousGet?.(path)
    );
    const { queryClient } = renderInApp(
      <CapabilitySourceDialog
        purpose="image_generation"
        server={{
          ...server,
          security_classification: {
            id: "classification",
            name: "Intern",
            description: null,
            security_level: 2
          }
        }}
        onClose={() => {}}
        onSaved={() => {}}
      />
    );
    expect(await screen.findByText("Intern")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Bildmodell"), { target: { value: "unclassified" } });
    expect(screen.queryByText("Intern")).toBeNull();
    expect(screen.getByText("Ingen klassificering")).toBeTruthy();
    await act(async () => queryClient.setQueryData(["image-models"], []));
    expect(screen.queryByText("Intern")).toBeNull();
  });

  it("keeps the saved classification fallback while the unchanged model's details are unavailable", async () => {
    const previousGet = api.GET.getMockImplementation();
    api.GET.mockImplementation((path: string) =>
      path === "/api/v1/image-models/" ? ok({ items: [] }) : previousGet?.(path)
    );
    renderInApp(
      <CapabilitySourceDialog
        purpose="image_generation"
        server={{
          ...server,
          security_classification: {
            id: "classification",
            name: "Intern",
            description: null,
            security_level: 2
          }
        }}
        onClose={() => {}}
        onSaved={() => {}}
      />
    );
    expect(await screen.findByText("Intern")).toBeTruthy();
  });
  it("selects a model created in place and saves the existing source with its draft intact", async () => {
    let created = false;
    const defaultGet = api.GET.getMockImplementation();
    api.GET.mockImplementation((path: string, options: unknown) => {
      if (path === "/api/v1/image-models/")
        return ok({
          items: created ? [model, { ...model, id: "new-image", name: "new-image" }] : [model]
        });
      if (path === "/api/v1/ai-models/")
        return ok({
          completion_models: [],
          embedding_models: [],
          transcription_models: [],
          image_models: [],
          rerank_models: []
        });
      if (path === "/api/v1/admin/model-providers/{provider_id}/models/")
        return ok([{ name: "new-image", display_name: "New image", mode: "image" }]);
      return defaultGet?.(path, options);
    });
    api.POST.mockImplementation((path: string) => {
      if (path.endsWith("/validate-model/")) return ok({ success: true });
      if (path === "/api/v1/admin/tenant-models/image/") {
        created = true;
        return ok({ ...model, id: "new-image" });
      }
      return ok(server);
    });
    renderInApp(
      <CapabilitySourceDialog
        purpose="image_generation"
        server={server}
        onClose={() => {}}
        onSaved={() => {}}
      />
    );
    fireEvent.change(screen.getByLabelText("Namn"), { target: { value: "Utkast kvar" } });
    fireEvent.click(screen.getByRole("button", { name: "Lägg till bildmodell" }));
    const wizard = await screen.findByRole("dialog", { name: "Lägg till modell" });
    fireEvent.click(
      await within(wizard).findByRole("button", { name: "Välj en befintlig leverantör" })
    );
    fireEvent.keyDown(within(wizard).getByRole("combobox", { name: /^Leverantör/ }), {
      key: "Enter"
    });
    fireEvent.click(await screen.findByRole("option", { name: "Provider" }));
    fireEvent.click(within(wizard).getByRole("button", { name: "Nästa" }));
    fireEvent.click(await within(wizard).findByRole("checkbox", { name: /New image/ }));
    fireEvent.click(within(wizard).getByRole("button", { name: "Lägg till 1 modell" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Lägg till modell" })).toBeNull()
    );
    await waitFor(() =>
      expect((screen.getByLabelText("Bildmodell") as HTMLSelectElement).value).toBe("new-image")
    );
    expect((screen.getByLabelText("Namn") as HTMLInputElement).value).toBe("Utkast kvar");
    expect(screen.queryByText("Modellen är inaktiverad.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/mcp-servers/{id}/", {
        params: { path: { id: "source" } },
        body: expect.objectContaining({ name: "Utkast kvar", image_model_id: "new-image" })
      })
    );
  });

  it("explains default replacement only when a new built-in source will activate for everyone", async () => {
    renderInApp(
      <CapabilitySourceDialog
        purpose="image_generation"
        replacesDefault="Current source"
        onClose={() => {}}
        onSaved={() => {}}
      />
    );
    fireEvent.change(screen.getByLabelText("Källa"), { target: { value: "builtin" } });
    expect(await screen.findByText("Ersätter Current source som standardkälla.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Målgrupp"), { target: { value: "groups" } });
    expect(screen.queryByText("Ersätter Current source som standardkälla.")).toBeNull();
  });
  it("shows selected defaults, readiness and inherited classification", async () => {
    renderInApp(
      <CapabilitySourceDialog
        purpose="image_generation"
        server={server}
        onClose={() => {}}
        onSaved={() => {}}
      />
    );
    expect(await screen.findByText(/1536x1024/)).toBeTruthy();
    expect(screen.getByText(/Hög/)).toBeTruthy();
    expect(screen.getByText("Ärvs från den valda bildmodellen.")).toBeTruthy();
    expect(screen.getByText("Intern")).toBeTruthy();
    expect(screen.getByText("Modellen är inaktiverad.")).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("keeps the source draft and returns focus when image model creation is cancelled", async () => {
    renderInApp(
      <CapabilitySourceDialog
        purpose="image_generation"
        server={server}
        onClose={() => {}}
        onSaved={() => {}}
      />
    );
    fireEvent.change(screen.getByLabelText("Namn"), { target: { value: "Utkast kvar" } });
    const add = await screen.findByRole("button", { name: "Lägg till bildmodell" });
    add.focus();
    fireEvent.click(add);
    const wizard = await screen.findByRole("dialog", { name: "Lägg till modell" });
    fireEvent.click(within(wizard).getByRole("button", { name: "Stäng" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Lägg till modell" })).toBeNull()
    );
    expect((screen.getByLabelText("Namn") as HTMLInputElement).value).toBe("Utkast kvar");
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Lägg till bildmodell" })
    );
    expect(api.POST).not.toHaveBeenCalled();
  });
});
