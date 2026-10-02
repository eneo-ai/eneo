// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { EditModelDialog } from "./edit-model-dialog";
import type { AdminModel } from "./models";

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const imageModel = {
  id: "i1",
  name: "gpt-image-1",
  nickname: "GPT Image 1",
  description: null,
  hosting: "usa",
  stability: "stable",
  open_source: false,
  cost_per_image: "0.04",
  default_size: "1536x1024",
  default_quality: "high",
  security_classification: null
} as unknown as AdminModel;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("EditModelDialog for an image model", () => {
  it("edits the per-image price and request defaults, never token fields", async () => {
    api.PUT.mockImplementation(() => ok({}));
    const onOpenChange = vi.fn();
    renderInApp(
      <EditModelDialog
        model={imageModel}
        kind="image"
        classifications={[]}
        securityEnabled={false}
        open
        onOpenChange={onOpenChange}
      />
    );
    const dialog = await screen.findByRole("dialog", { name: "Redigera modell" });
    expect(within(dialog).queryByLabelText(/^Max indatatokens/)).toBeNull();
    expect(within(dialog).queryByLabelText(/^Pris per minut/)).toBeNull();
    // The model id cannot be renamed; the request defaults show their labels.
    expect(
      (within(dialog).getByLabelText("Modellidentifierare") as HTMLInputElement).readOnly
    ).toBe(true);
    expect(within(dialog).getByRole("combobox", { name: "Standardstorlek" }).textContent).toBe(
      "1536x1024"
    );
    expect(within(dialog).getByRole("combobox", { name: "Standardkvalitet" }).textContent).toBe(
      "Hög"
    );
    await expectNoAxeViolations(dialog);

    const cost = within(dialog).getByLabelText(/^Pris per bild/) as HTMLInputElement;
    expect(cost.value).toBe("0.04");
    fireEvent.change(cost, { target: { value: "0.08" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.PUT).toHaveBeenCalledWith("/api/v1/admin/tenant-models/image/{model_id}/", {
        params: { path: { model_id: "i1" } },
        body: {
          display_name: "GPT Image 1",
          description: null,
          hosting: "usa",
          open_source: false,
          stability: "stable",
          cost_per_image: 0.08,
          default_size: "1536x1024",
          default_quality: "high",
          security_classification: null
        }
      })
    );
    expect(toast.success).toHaveBeenCalledWith("Modellen har uppdaterats");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
