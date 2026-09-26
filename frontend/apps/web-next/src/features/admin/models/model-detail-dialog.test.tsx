// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { AdminModel } from "./models";

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () =>
      Promise.resolve({
        data: {
          items: [
            ["a1", "Upphandlingsassistenten", "assistant"],
            ["p1", "Protokollsammanfattaren", "app"],
            ["s1", "Ärendesortering", "service"],
            ["t1", "Avtalsgranskare", "assistant_template"],
            ["t2", "Mötesprotokoll", "app_template"],
            ["x1", "Något nytt", "workflow"]
          ].map(([entity_id, entity_name, entity_type]) => ({
            entity_id,
            entity_name,
            entity_type,
            space_name: "Upphandling",
            owner_name: "Anna Lind"
          })),
          total: 6
        },
        response: new Response("{}")
      })
  }
}));

import { ModelDetailDialog } from "./model-detail-dialog";

afterEach(cleanup);

const model = { id: "model-1", name: "gpt-5", nickname: "GPT-5" } as AdminModel;

describe("ModelDetailDialog", () => {
  it("names the usage table by the text above it", async () => {
    renderInApp(<ModelDetailDialog model={model} kind="completion" open onOpenChange={() => {}} />);

    const dialog = await screen.findByRole("dialog", { name: "GPT-5" });
    // Radix tabs switch on mouse down.
    fireEvent.mouseDown(within(dialog).getByRole("tab", { name: "Användning" }));
    const table = await within(dialog).findByRole("table", {
      name: "Resurser som använder denna modell"
    });
    expect(within(table).getByText("Upphandlingsassistenten")).toBeTruthy();
  });

  it("says what kind of resource each one is, in Swedish", async () => {
    renderInApp(<ModelDetailDialog model={model} kind="completion" open onOpenChange={() => {}} />);

    const dialog = await screen.findByRole("dialog", { name: "GPT-5" });
    fireEvent.mouseDown(within(dialog).getByRole("tab", { name: "Användning" }));
    const table = await within(dialog).findByRole("table", {
      name: "Resurser som använder denna modell"
    });
    const types = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell")[1]!.textContent);
    // A type the app does not know yet shows as the API sends it.
    expect(types).toEqual(["Assistent", "App", "Tjänst", "Assistentmall", "Appmall", "workflow"]);
  });
});
