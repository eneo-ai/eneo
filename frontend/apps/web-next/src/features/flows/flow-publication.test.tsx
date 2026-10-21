// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { flowFixture } from "./flow-fixtures";
import { FlowPublication } from "./flow-publication";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("publishes directly with the displayed revision", async () => {
  api.POST.mockResolvedValue({ data: flowFixture, response: new Response("{}") });
  const saved = vi.fn();
  const { container } = renderInApp(<FlowPublication flow={flowFixture} onSaved={saved} />);
  fireEvent.click(screen.getByRole("button", { name: "Publicera" }));
  await waitFor(() => expect(saved).toHaveBeenCalledWith(flowFixture));
  expect(api.POST).toHaveBeenCalledWith("/api/v1/flows/{id}/publish/", {
    params: { path: { id: flowFixture.id } },
    body: { expected_revision: flowFixture.revision }
  });
  await expectNoAxeViolations(container);
});

it("confirms unpublication and keeps the revision fence", async () => {
  api.POST.mockResolvedValue({
    data: { ...flowFixture, published_version: null },
    response: new Response("{}")
  });
  const saved = vi.fn();
  renderInApp(<FlowPublication flow={flowFixture} onSaved={saved} />);
  fireEvent.click(screen.getByRole("button", { name: "Avpublicera" }));
  const dialog = await screen.findByRole("alertdialog");
  await expectNoAxeViolations(dialog);
  const buttons = screen.getAllByRole("button", { name: "Avpublicera" });
  fireEvent.click(buttons[buttons.length - 1]!);
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(api.POST).toHaveBeenCalledWith("/api/v1/flows/{id}/unpublish/", {
    params: { path: { id: flowFixture.id } },
    body: { expected_revision: flowFixture.revision }
  });
});
