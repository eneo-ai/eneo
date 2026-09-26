// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const template = (id: string, name: string) => ({
  id,
  name,
  category: "Upphandling",
  completion_model_name: null,
  usage_count: 2,
  is_default: false,
  original_snapshot: null,
  deleted_at: null
});

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      const items =
        path === "/api/v1/admin/templates/assistants/"
          ? [template("a1", "Upphandlingsassistent")]
          : path === "/api/v1/admin/templates/apps/"
            ? [template("p1", "Protokollsammanfattare")]
            : path.endsWith("/deleted")
              ? [template("d1", "Gammal mall")]
              : [];
      return Promise.resolve({ data: { items }, response: new Response("{}") });
    }
  }
}));

import { TemplatesPage } from "./templates-page";

afterEach(cleanup);

describe("TemplatesPage", () => {
  it("names each tab's table after the tab", async () => {
    const { container } = renderInApp(<TemplatesPage />);

    const assistants = await screen.findByRole("table", { name: "Assistenter" });
    expect(within(assistants).getByText("Upphandlingsassistent")).toBeTruthy();
    // Each row's menu says whose it is.
    expect(
      within(assistants).getByRole("button", { name: "Fler åtgärder för Upphandlingsassistent" })
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    // Radix tabs switch on mouse down.
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Appar" }));
    const apps = await screen.findByRole("table", { name: "Appar" });
    expect(within(apps).getByText("Protokollsammanfattare")).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Borttagna mallar" }));
    const deleted = await screen.findByRole("table", { name: "Borttagna mallar" });
    expect(within(deleted).getAllByText("Gammal mall")).toHaveLength(2);
  });
});
