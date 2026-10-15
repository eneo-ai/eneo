// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
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
const imageModel = {
  id: "image-1",
  name: "gpt-image-1",
  nickname: "GPT Image 1",
  hosting: "usa",
  default_size: "1024x1024",
  default_quality: "high",
  used_by_mcp_servers: [{ id: "cap-1", name: "Bildgenerering", purpose: "image_generation" }]
} as AdminModel;

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

  it("shows an image model's request defaults and sources without a usage tab", async () => {
    renderInApp(<ModelDetailDialog model={imageModel} kind="image" open onOpenChange={() => {}} />);

    const dialog = await screen.findByRole("dialog", { name: "GPT Image 1" });
    // No usage endpoint for image models: the properties stand alone.
    expect(within(dialog).queryByRole("tab")).toBeNull();
    expect(within(dialog).getByText("Standardstorlek").nextElementSibling?.textContent).toBe(
      "1024x1024"
    );
    expect(within(dialog).getByText("Standardkvalitet").nextElementSibling?.textContent).toBe(
      "Hög"
    );
    const sources = within(dialog).getByText("Används av Bildgenerering").nextElementSibling;
    expect(within(sources as HTMLElement).getByRole("listitem").textContent).toBe("Bildgenerering");
    await expectNoAxeViolations(dialog);
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
