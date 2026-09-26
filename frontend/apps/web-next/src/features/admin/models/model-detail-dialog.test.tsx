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
            {
              entity_id: "a1",
              entity_name: "Upphandlingsassistenten",
              entity_type: "assistant",
              space_name: "Upphandling",
              owner_name: "Anna Lind"
            }
          ],
          total: 1
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
});
