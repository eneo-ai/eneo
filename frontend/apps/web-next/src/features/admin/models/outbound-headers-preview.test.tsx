// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
import { OutboundHeadersPreview } from "./outbound-headers-preview";
const ok = (data: unknown) => ({ data, response: new Response("{}") });
const users = (email: string, id = "u1") =>
  ok({
    items: [{ id, email }],
    metadata: { page: 1, page_size: 8, total_count: 1, total_pages: 1 }
  });
const search = (value: string) =>
  fireEvent.change(screen.getByLabelText(/^Sök på e-post/), { target: { value } });
async function choose() {
  search("ann");
  fireEvent.click(await screen.findByRole("button", { name: "anna@example.test" }));
}
beforeEach(() => {
  vi.resetAllMocks();
  api.GET.mockResolvedValue(users("anna@example.test"));
  api.POST.mockResolvedValue(
    ok({
      user_id: "u1",
      blocked: false,
      headers: [
        { name: "X-Region", state: "resolved", value: "north", secret: false },
        { name: "X-Secret", state: "resolved", value: "should-never-render", secret: true }
      ]
    })
  );
});

describe("outbound header preview", () => {
  it("searches a bounded tenant user page and previews without displaying secret values", async () => {
    renderInApp(<OutboundHeadersPreview providerId="p1" hasUnsavedChanges={false} />);
    search("an");
    await act(() => new Promise((resolve) => setTimeout(resolve, 300)));
    expect(api.GET).not.toHaveBeenCalled();
    await choose();
    expect(api.GET).toHaveBeenCalledWith(
      "/api/v1/admin/users/",
      expect.objectContaining({
        params: {
          query: expect.objectContaining({
            search_email: "ann",
            page_size: 8,
            state_filter: undefined
          })
        }
      })
    );
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Förhandsgranska" }));
    fireEvent.click(screen.getByRole("button", { name: "Förhandsgranska" }));
    expect(await screen.findByText("north")).toBeTruthy();
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/admin/model-providers/{provider_id}/outbound-headers/preview/",
      { params: { path: { provider_id: "p1" } }, body: { user_id: "u1" } }
    );
    expect(screen.queryByText("should-never-render")).toBeNull();
    expect(screen.getByText(/Värdet visas inte/)).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("keeps search failure distinct from an empty result and retries the same query", async () => {
    api.GET.mockRejectedValueOnce(new Error("offline"));
    renderInApp(<OutboundHeadersPreview providerId="p1" hasUnsavedChanges={false} />);
    search("ann");
    const retry = await screen.findByRole("button", { name: "Försök igen" });
    expect(screen.queryByText("Inga användare hittades")).toBeNull();
    fireEvent.click(retry);
    expect(await screen.findByRole("button", { name: "anna@example.test" })).toBeTruthy();
    expect(api.GET).toHaveBeenCalledTimes(2);
  });

  it("does not show stale search results or preview results after selecting another user", async () => {
    let finishSearch: ((value: unknown) => void) | undefined;
    api.GET.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishSearch = resolve;
        })
    );
    renderInApp(<OutboundHeadersPreview providerId="p1" hasUnsavedChanges={false} />);
    search("old");
    await waitFor(() => expect(api.GET).toHaveBeenCalledTimes(1));
    await choose();
    await act(async () => finishSearch?.(users("old@example.test", "old")));
    expect(screen.queryByRole("button", { name: "old@example.test" })).toBeNull();
    let finishPreview: ((value: unknown) => void) | undefined;
    api.POST.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishPreview = resolve;
        })
    );
    fireEvent.click(screen.getByRole("button", { name: "Förhandsgranska" }));
    fireEvent.click(screen.getByRole("button", { name: "Ändra" }));
    expect(document.activeElement).toBe(screen.getByLabelText(/^Sök på e-post/));
    await act(async () =>
      finishPreview?.(
        ok({
          user_id: "u1",
          blocked: false,
          headers: [{ name: "X-Old", value: "stale", state: "resolved", secret: false }]
        })
      )
    );
    expect(screen.queryByText("stale")).toBeNull();
  });

  it("explains blocked requests and suppresses preview while the form is dirty", async () => {
    api.POST.mockResolvedValueOnce(
      ok({
        user_id: "u1",
        blocked: true,
        blocked_reason: "decryption_failed",
        headers: [
          {
            name: "X-Employee",
            state: "missing",
            secret: false,
            policy: "fail",
            missing_dynamic_values: ["user.employeeNumber"]
          }
        ]
      })
    );
    const view = renderInApp(<OutboundHeadersPreview providerId="p1" hasUnsavedChanges={false} />);
    await choose();
    fireEvent.click(screen.getByRole("button", { name: "Förhandsgranska" }));
    expect(await screen.findByText(/inte kan läsas|inte läsas|inte att läsa/)).toBeTruthy();
    expect(screen.getByText(/user.employeeNumber/)).toBeTruthy();
    view.rerender(<OutboundHeadersPreview providerId="p1" hasUnsavedChanges />);
    expect(screen.getByText("Spara dina ändringar för att förhandsgranska dem.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Förhandsgranska" })).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("shows both destination and stored-secret recovery problems", async () => {
    api.POST.mockResolvedValueOnce(
      ok({
        user_id: "u1",
        blocked: true,
        destination_problem: "not_allowed",
        blocked_reason: "decryption_failed",
        headers: []
      })
    );
    renderInApp(<OutboundHeadersPreview providerId="p1" hasUnsavedChanges={false} />);
    await choose();
    fireEvent.click(screen.getByRole("button", { name: "Förhandsgranska" }));
    expect(await screen.findByText(/endpointen är inte ett tillåtet mål/)).toBeTruthy();
    expect(screen.getByText(/Ett lagrat hemligt headervärde kan inte läsas/)).toBeTruthy();
  });
});
