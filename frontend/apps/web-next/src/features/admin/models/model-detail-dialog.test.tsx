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
const rerankModel = {
  id: "rerank-1",
  name: "Qwen/Qwen3-Reranker-4B",
  nickname: "Qwen Reranker",
  candidate_factor: 3,
  max_candidates: 250
} as AdminModel;

describe("ModelDetailDialog", () => {
  it.each([
    [true, "Ja"],
    [false, "Nej"]
  ])("states live transcription %s in a transcription model's details", async (on, answer) => {
    renderInApp(
      <ModelDetailDialog
        model={{ ...model, provider_type: "hosted_vllm", supports_realtime: on } as AdminModel}
        kind="transcription"
        open
        onOpenChange={() => {}}
      />
    );
    const term = await screen.findByText("Livetranskribering", { selector: "dt" });
    expect(term.nextElementSibling?.textContent).toBe(answer);
  });

  it("formats the context window in the UI language", async () => {
    renderInApp(
      <ModelDetailDialog
        model={{ ...model, max_input_tokens: 12345 } as AdminModel}
        kind="completion"
        open
        onOpenChange={() => {}}
      />
    );
    expect(await screen.findByText("12 345")).toBeTruthy();
  });

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

  it("shows a rerank model's candidate settings without a usage tab", async () => {
    renderInApp(
      <ModelDetailDialog model={rerankModel} kind="rerank" open onOpenChange={() => {}} />
    );

    const dialog = await screen.findByRole("dialog", { name: "Qwen Reranker" });
    // No usage endpoint for rerank models either.
    expect(within(dialog).queryByRole("tab")).toBeNull();
    expect(
      within(dialog).getByText("Kandidater per efterfrågad chunk").nextElementSibling?.textContent
    ).toBe("3");
    expect(
      within(dialog).getByText("Max antal kandidater per sökning").nextElementSibling?.textContent
    ).toBe("250");
    expect(within(dialog).queryByText("Funktioner")).toBeNull();
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

it("shows completion metadata and offers edit and migration from a deprecated model", async () => {
  const onEdit = vi.fn();
  const onMigrate = vi.fn();
  renderInApp(
    <ModelDetailDialog
      model={
        {
          ...model,
          name: "provider/gpt-5",
          max_input_tokens: 128000,
          max_output_tokens: 4096,
          vision: true,
          reasoning: true,
          supports_tool_calling: true,
          hosting: "usa",
          open_source: false,
          org: "OpenAI",
          family: "gpt",
          description: "Supports the municipality",
          hf_link: "https://huggingface.co/example/model",
          input_cost_per_token: "0.000005",
          output_cost_per_token: "0.00001",
          is_deprecated: true,
          security_classification: {
            id: "s1",
            name: "Intern",
            description: null,
            security_level: 1
          }
        } as AdminModel
      }
      kind="completion"
      open
      onOpenChange={vi.fn()}
      onEdit={onEdit}
      onMigrate={onMigrate}
    />
  );
  const dialog = screen.getByRole("dialog", { name: "GPT-5" });
  expect(within(dialog).getByText("Modellidentifierare").nextElementSibling?.textContent).toBe(
    "provider/gpt-5"
  );
  expect(within(dialog).getByText("Max utdatatokens").nextElementSibling?.textContent).toBe(
    "4\u00a0096"
  );
  expect(within(dialog).getByText("Hosting-region").nextElementSibling?.textContent).toBe("USA");
  expect(within(dialog).getByText("Leverantör").nextElementSibling?.textContent).toBe("OpenAI");
  expect(within(dialog).getByText("Öppen källkod").nextElementSibling?.textContent).toBe("Nej");
  expect(within(dialog).getByText("Säkerhetsklassificering").nextElementSibling?.textContent).toBe(
    "Intern"
  );
  expect(within(dialog).getByText("Verktyg")).toBeTruthy();
  expect(
    within(dialog).getByRole("link", { name: "Visa på HuggingFace" }).getAttribute("href")
  ).toBe("https://huggingface.co/example/model");
  fireEvent.click(within(dialog).getByRole("button", { name: "Redigera" }));
  expect(onEdit).toHaveBeenCalledOnce();
  fireEvent.click(within(dialog).getByRole("button", { name: "Migrera" }));
  expect(onMigrate).toHaveBeenCalledOnce();
  await expectNoAxeViolations(dialog);
});

it("opens embedding details without requesting an unsupported usage endpoint", () => {
  renderInApp(
    <ModelDetailDialog
      model={
        {
          ...model,
          dimensions: 1024,
          max_input: 512,
          family: "e5",
          open_source: true
        } as AdminModel
      }
      kind="embedding"
      open
      onOpenChange={vi.fn()}
    />
  );
  const dialog = screen.getByRole("dialog", { name: "GPT-5" });
  expect(within(dialog).getByText("Dimensioner").nextElementSibling?.textContent).toBe(
    "1\u00a0024"
  );
  expect(within(dialog).getByText("Modellfamilj").nextElementSibling?.textContent).toBe(
    "E5 (HuggingFace)"
  );
  expect(within(dialog).queryByRole("tab", { name: "Användning" })).toBeNull();
});
