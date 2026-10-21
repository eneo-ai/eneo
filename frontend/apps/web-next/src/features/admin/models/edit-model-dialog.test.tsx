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

it("discards cancelled edits and loads the current model on reopen", async () => {
  api.PUT.mockImplementation(() => ok({}));
  const props = {
    model: imageModel,
    kind: "image" as const,
    classifications: [],
    securityEnabled: false,
    onOpenChange: vi.fn()
  };
  const { rerender } = renderInApp(<EditModelDialog {...props} open />);
  fireEvent.change(screen.getByLabelText(/^Pris per bild/), { target: { value: "99" } });
  rerender(<EditModelDialog {...props} open={false} />);
  rerender(
    <EditModelDialog
      {...props}
      model={{ ...imageModel, cost_per_image: "0.08" } as AdminModel}
      open
    />
  );
  expect(((await screen.findByLabelText(/^Pris per bild/)) as HTMLInputElement).value).toBe("0.08");
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

describe("EditModelDialog for a forecast model", () => {
  const forecastModel = {
    id: "f1",
    name: "default",
    nickname: "Timestral",
    org: "Mistral AI",
    open_source: true,
    security_classification: null
  } as unknown as AdminModel;

  it("sends only what the admin changed, so a rename keeps a class set meanwhile", async () => {
    api.POST.mockImplementation(() => ok({}));
    const onOpenChange = vi.fn();
    renderInApp(
      <EditModelDialog
        model={forecastModel}
        kind="forecast"
        classifications={[{ id: "s3", name: "Klass 3", security_level: 3 } as never]}
        securityEnabled
        open
        onOpenChange={onOpenChange}
      />
    );
    const dialog = await screen.findByRole("dialog", { name: "Redigera modell" });
    expect(
      (within(dialog).getByLabelText("Modellidentifierare") as HTMLInputElement).readOnly
    ).toBe(true);
    // Eneo sets the rest: the endpoint takes the name and the class.
    for (const label of ["Beskrivning", "Modellfamilj", "Hosting-region", "Stabilitet"]) {
      expect(within(dialog).queryByLabelText(label)).toBeNull();
    }
    expect(within(dialog).queryByText("Öppen källkod")).toBeNull();
    await expectNoAxeViolations(dialog);

    fireEvent.change(within(dialog).getByLabelText("Visningsnamn"), {
      target: { value: "  Prognosmodellen " }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/forecast-models/{id}/", {
        params: { path: { id: "f1" } },
        body: { display_name: "Prognosmodellen" }
      })
    );
    expect(api.PUT).not.toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith("Modellen har uppdaterats");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("sends a class the admin chose or cleared, and not the name it left alone", async () => {
    const classified = {
      ...forecastModel,
      security_classification: { id: "s3", name: "Klass 3", security_level: 3 }
    } as unknown as AdminModel;
    api.POST.mockImplementation(() => ok({}));
    renderInApp(
      <EditModelDialog
        model={classified}
        kind="forecast"
        classifications={[{ id: "s3", name: "Klass 3", security_level: 3 } as never]}
        securityEnabled
        open
        onOpenChange={vi.fn()}
      />
    );
    const dialog = await screen.findByRole("dialog", { name: "Redigera modell" });
    fireEvent.click(within(dialog).getByRole("combobox", { name: /Säkerhetsklass/ }));
    fireEvent.click(await screen.findByRole("option", { name: /Ingen/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/forecast-models/{id}/", {
        params: { path: { id: "f1" } },
        body: { security_classification: null }
      })
    );
  });

  it("keeps what it opened with when the model is refreshed while it is open", async () => {
    api.POST.mockImplementation(() => ok({}));
    const dialogFor = (model: AdminModel) => (
      <EditModelDialog
        model={model}
        kind="forecast"
        classifications={[{ id: "s3", name: "Klass 3", security_level: 3 } as never]}
        securityEnabled
        open
        onOpenChange={vi.fn()}
      />
    );
    const { rerender } = renderInApp(dialogFor(forecastModel));
    const dialog = await screen.findByRole("dialog", { name: "Redigera modell" });
    // Another admin classifies the model; the refetched model reaches the open form.
    rerender(
      dialogFor({
        ...forecastModel,
        security_classification: { id: "s3", name: "Klass 3", security_level: 3 }
      } as unknown as AdminModel)
    );
    fireEvent.change(within(dialog).getByLabelText("Visningsnamn"), {
      target: { value: "Prognosmodellen" }
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    // Only the rename: the class the other admin set is left as it is.
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/forecast-models/{id}/", {
        params: { path: { id: "f1" } },
        body: { display_name: "Prognosmodellen" }
      })
    );
  });
});
