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

const rerankModel = {
  id: "r1",
  name: "Qwen/Qwen3-Reranker-4B",
  nickname: "Qwen Reranker",
  description: null,
  family: "qwen",
  hosting: "swe",
  stability: "stable",
  open_source: true,
  candidate_factor: 5,
  max_candidates: 100,
  security_classification: null
} as unknown as AdminModel;

function renderRerankDialog(onOpenChange = vi.fn()) {
  api.PUT.mockImplementation(() => ok({}));
  renderInApp(
    <EditModelDialog
      model={rerankModel}
      kind="rerank"
      classifications={[]}
      securityEnabled={false}
      open
      onOpenChange={onOpenChange}
    />
  );
  return screen.findByRole("dialog", { name: "Redigera modell" });
}

describe("EditModelDialog for a rerank model", () => {
  it("edits the candidate factor and cap, never token or price fields", async () => {
    const onOpenChange = vi.fn();
    const dialog = await renderRerankDialog(onOpenChange);
    expect(within(dialog).queryByLabelText(/^Max indatatokens/)).toBeNull();
    expect(within(dialog).queryByLabelText(/^Pris per/)).toBeNull();
    expect(
      (within(dialog).getByLabelText("Modellidentifierare") as HTMLInputElement).readOnly
    ).toBe(true);
    // The rerank API takes no family, so the field cannot promise a change.
    const family = within(dialog).getByLabelText("Modellfamilj") as HTMLInputElement;
    expect([family.value, family.readOnly]).toEqual(["qwen", true]);
    await expectNoAxeViolations(dialog);

    const factor = within(dialog).getByLabelText(
      "Kandidater per efterfrågad chunk"
    ) as HTMLInputElement;
    const cap = within(dialog).getByLabelText(
      "Max antal kandidater per sökning"
    ) as HTMLInputElement;
    expect([factor.value, cap.value]).toEqual(["5", "100"]);
    fireEvent.change(factor, { target: { value: "3" } });
    fireEvent.change(cap, { target: { value: "250" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.PUT).toHaveBeenCalledWith("/api/v1/admin/tenant-models/rerank/{model_id}/", {
        params: { path: { model_id: "r1" } },
        body: {
          display_name: "Qwen Reranker",
          description: null,
          hosting: "swe",
          open_source: true,
          stability: "stable",
          candidate_factor: 3,
          max_candidates: 250,
          security_classification: null
        }
      })
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it.each([
    ["Kandidater per efterfrågad chunk", "21", "Ange ett heltal från 1 till 20."],
    ["Kandidater per efterfrågad chunk", "2.5", "Ange ett heltal från 1 till 20."],
    ["Max antal kandidater per sökning", "0", "Ange ett heltal från 1 till 1000."],
    ["Max antal kandidater per sökning", "", "Ange ett heltal från 1 till 1000."]
  ])(
    "refuses %s = %j with the reason at the field and focus on it",
    async (label, value, problem) => {
      const dialog = await renderRerankDialog();
      const field = within(dialog).getByLabelText(label) as HTMLInputElement;
      fireEvent.change(field, { target: { value } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

      const error = await within(dialog).findByText(problem);
      expect(field.getAttribute("aria-invalid")).toBe("true");
      expect(field.getAttribute("aria-describedby")?.split(" ")).toContain(
        error.closest("[id]")!.id
      );
      expect(document.activeElement).toBe(field);
      expect(api.PUT).not.toHaveBeenCalled();
    }
  );

  it("moves focus to the first of two invalid fields", async () => {
    const dialog = await renderRerankDialog();
    const factor = within(dialog).getByLabelText("Kandidater per efterfrågad chunk");
    const cap = within(dialog).getByLabelText("Max antal kandidater per sökning");
    fireEvent.change(factor, { target: { value: "0" } });
    fireEvent.change(cap, { target: { value: "5000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Spara" }));

    await within(dialog).findByText("Ange ett heltal från 1 till 1000.");
    expect(within(dialog).getByText("Ange ett heltal från 1 till 20.")).toBeTruthy();
    expect(document.activeElement).toBe(factor);
    await expectNoAxeViolations(dialog);
  });
});

const completionModel = {
  ...imageModel,
  id: "c1",
  name: "gpt-5",
  nickname: "GPT 5",
  max_input_tokens: 128000,
  max_output_tokens: 4096,
  is_org_default: true
} as AdminModel;

it("requires positive whole completion token budgets and can clear the tenant default", async () => {
  api.PUT.mockImplementation(() => ok({}));
  renderInApp(
    <EditModelDialog
      model={completionModel}
      kind="completion"
      classifications={[]}
      securityEnabled={false}
      open
      onOpenChange={vi.fn()}
    />
  );
  const input = screen.getByLabelText("Max indatatokens");
  const output = screen.getByLabelText("Max utdatatokens");
  fireEvent.change(input, { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  expect(api.PUT).not.toHaveBeenCalled();
  expect(screen.getByText("Ange ett heltal större än 0.")).toBeTruthy();
  expect(document.activeElement).toBe(input);
  fireEvent.change(input, { target: { value: "128000" } });
  fireEvent.change(output, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  expect(api.PUT).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(output);
  fireEvent.change(output, { target: { value: "4096" } });
  fireEvent.click(screen.getByRole("switch", { name: "Ange som standardmodell" }));
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  await waitFor(() =>
    expect(api.PUT).toHaveBeenCalledWith("/api/v1/admin/tenant-models/completion/{model_id}/", {
      params: { path: { model_id: "c1" } },
      body: expect.objectContaining({
        max_input_tokens: 128000,
        max_output_tokens: 4096,
        is_default: false
      })
    })
  );
});

const transcriptionModel = (providerType: string | null, supportsRealtime = false) =>
  ({
    id: "t1",
    name: "pianissimo-sv",
    nickname: "Pianissimo",
    description: null,
    hosting: "swe",
    stability: "stable",
    open_source: false,
    cost_per_minute: null,
    provider_id: "p1",
    provider_type: providerType,
    supports_realtime: supportsRealtime,
    security_classification: null
  }) as unknown as AdminModel;

function editLiveTranscription(model: AdminModel) {
  api.PUT.mockImplementation(() => ok({}));
  renderInApp(
    <EditModelDialog
      model={model}
      kind="transcription"
      classifications={[]}
      securityEnabled={false}
      open
      onOpenChange={vi.fn()}
    />
  );
  return screen.getByRole("switch", { name: "Livetranskribering" });
}

/** The texts a control's aria-describedby points at. */
const descriptions = (element: HTMLElement) =>
  (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent);

describe("live transcription on a transcription model", () => {
  // "vllm" is the backend's alias for hosted_vllm, and a provider created
  // through the API keeps the type it was given.
  it.each(["hosted_vllm", "vllm"])("turns it on for a %s provider", async (providerType) => {
    const toggle = editLiveTranscription(transcriptionModel(providerType));
    expect((toggle as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText("Kräver en leverantör av typen vLLM.")).toBeNull();

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.PUT).toHaveBeenCalledWith(
        "/api/v1/admin/tenant-models/transcription/{model_id}/",
        {
          params: { path: { model_id: "t1" } },
          body: expect.objectContaining({ supports_realtime: true })
        }
      )
    );
  });

  it.each(["openai", null])("says why it is unavailable for provider type %s", (providerType) => {
    const toggle = editLiveTranscription(transcriptionModel(providerType));
    expect((toggle as HTMLButtonElement).disabled).toBe(true);
    expect(descriptions(toggle)).toContain("Kräver en leverantör av typen vLLM.");
  });

  it("states the flag on every save, so turning it off reaches the server", async () => {
    const toggle = editLiveTranscription(transcriptionModel("hosted_vllm", true));
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    await expectNoAxeViolations(screen.getByRole("dialog"));

    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));

    await waitFor(() =>
      expect(api.PUT.mock.calls[0]?.[1]?.body).toMatchObject({ supports_realtime: false })
    );
  });
});

it("offers validated hosting and E5 choices while preserving other embedding metadata", async () => {
  api.PUT.mockImplementation(() => ok({}));
  renderInApp(
    <EditModelDialog
      model={{ ...imageModel, id: "e1", family: "openai", dimensions: 1024, max_input: 512 }}
      kind="embedding"
      classifications={[]}
      securityEnabled={false}
      open
      onOpenChange={vi.fn()}
    />
  );
  fireEvent.keyDown(screen.getByRole("combobox", { name: "Modellfamilj" }), { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("option", { name: "E5 (HuggingFace)" }));
  fireEvent.keyDown(screen.getByRole("combobox", { name: "Hosting-region" }), { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("option", { name: "Sverige" }));
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  await waitFor(() =>
    expect(api.PUT).toHaveBeenCalledWith("/api/v1/admin/tenant-models/embedding/{model_id}/", {
      params: { path: { model_id: "e1" } },
      body: expect.objectContaining({
        family: "e5",
        hosting: "swe",
        max_input: 512,
        dimensions: 1024
      })
    })
  );
  expect(api.PUT.mock.calls[0]?.[1]?.body).not.toHaveProperty("is_default");
});
