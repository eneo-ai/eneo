// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import { setRoute } from "@/test/navigation";
import { ServiceDetail } from "./service-detail";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", () => ({ useSpace: () => ({ routeId: "space-1" }) }));
vi.mock("./playground", () => ({ ServicePlayground: () => <p>Testvy</p> }));
vi.mock("./editor/service-editor", () => ({ ServiceEditor: () => <p>Inställningsvy</p> }));
afterEach(cleanup);

it("follows external same-route tab changes without retaining an unavailable settings tab", () => {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["services", "service-1"], { name: "Protokoll", permissions: ["edit"] });
  const { rerender } = renderInApp(<ServiceDetail serviceId="service-1" />, {
    queryClient,
    route: "/spaces/space-1/services/service-1"
  });
  expect(screen.getByRole("tabpanel").textContent).toBe("Testvy");
  setRoute("/spaces/space-1/services/service-1?tab=settings");
  rerender(<ServiceDetail serviceId="service-1" />);
  expect(screen.getByRole("tabpanel").textContent).toBe("Inställningsvy");
  queryClient.setQueryData(["services", "service-1"], { name: "Protokoll", permissions: [] });
  rerender(<ServiceDetail serviceId="service-1" />);
  expect(screen.getByRole("tabpanel").textContent).toBe("Testvy");
});
