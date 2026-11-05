// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Space } from "@/features/spaces/space";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { App } from "../apps";
import { SecuritySection } from "./security-section";

const state = vi.hoisted(() => ({ space: null as unknown as Space }));
const api = vi.hoisted(() => ({ PATCH: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space) };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
const app = { id: "app-1", data_retention_days: 14, permissions: ["read", "edit"] } as App;
beforeEach(() => {
  api.PATCH.mockResolvedValue({ data: app, response: new Response("{}") });
});
const retention = () => screen.getByRole("textbox", { name: "Gallring av konversationshistorik" });

it("shows retention read-only to an app editor who cannot edit its shared space", async () => {
  state.space = makeSpace({ permissions: ["read"] });
  const { container } = renderInApp(<SecuritySection app={app} />);
  expect((retention() as HTMLInputElement).value).toBe("14");
  expect(retention().hasAttribute("disabled")).toBe(true);
  const hint = screen.getByText("Endast administratörer för utrymmet kan ändra gallringen.");
  expect(retention().getAttribute("aria-describedby")).toContain(hint.id);
  expect(api.PATCH).not.toHaveBeenCalled();
  await expectNoAxeViolations(container);
});

it.each([
  { personal: false, permissions: ["read", "edit"] },
  { personal: true, permissions: ["read"] }
] as const)(
  "permits retention changes for personal=$personal with $permissions",
  async ({ personal, permissions }) => {
    state.space = makeSpace({ permissions: [...permissions], overrides: { personal } });
    renderInApp(<SecuritySection app={app} />);
    expect(retention().hasAttribute("disabled")).toBe(false);
    fireEvent.change(retention(), { target: { value: "30" } });
    fireEvent.blur(retention());
    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith("/api/v1/apps/{id}/", {
        params: { path: { id: "app-1" } },
        body: { data_retention_days: 30 }
      })
    );
  }
);

it("preserves the shared 2555-day bound and a deliberate clear to inherited retention", async () => {
  state.space = makeSpace({ overrides: { data_retention_days: 90 } });
  renderInApp(<SecuritySection app={app} />);
  expect(retention().getAttribute("placeholder")).toBe("90 dagar");
  fireEvent.change(retention(), { target: { value: "2556" } });
  fireEvent.blur(retention());
  expect(retention().getAttribute("aria-invalid")).toBe("true");
  expect(api.PATCH).not.toHaveBeenCalled();
  fireEvent.change(retention(), { target: { value: "" } });
  fireEvent.blur(retention());
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/apps/{id}/", {
      params: { path: { id: "app-1" } },
      body: { data_retention_days: null }
    })
  );
  fireEvent.change(retention(), { target: { value: "2555" } });
  fireEvent.blur(retention());
  await waitFor(() =>
    expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/apps/{id}/", {
      params: { path: { id: "app-1" } },
      body: { data_retention_days: 2555 }
    })
  );
});

it("does not flush a dirty retention draft after space-edit permission is revoked", async () => {
  state.space = makeSpace();
  const { queryClient, unmount } = renderInApp(<SecuritySection app={app} />);
  fireEvent.change(retention(), { target: { value: "30" } });
  await act(async () => {
    queryClient.setQueryData(["spaces", "space-1"], makeSpace({ permissions: ["read"] }));
  });
  await waitFor(() => expect(retention().hasAttribute("disabled")).toBe(true));
  unmount();
  expect(api.PATCH).not.toHaveBeenCalled();
});
