// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeAll, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { EmbeddingModelSelect } from "./embedding-model-select";
import type { EmbeddingModel } from "./knowledge";

const model = (id: string, name: string): EmbeddingModel => ({
  id,
  name,
  is_deprecated: false,
  open_source: false,
  stability: "stable"
});

it("is named by its visible label", () => {
  renderInApp(
    <EmbeddingModelSelect
      models={[model("e5", "multilingual-e5-large"), model("ada", "text-embedding-3-large")]}
      value="e5"
      onChange={() => {}}
    />
  );

  expect(screen.getByRole("combobox", { name: "Embedding-modell" })).toBeTruthy();
});

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(cleanup);

it("distinguishes equal nicknames by their hosting providers", async () => {
  renderInApp(
    <EmbeddingModelSelect
      models={[
        { ...model("a", "raw-a"), nickname: "Sökmodell", provider_name: "Berget" },
        { ...model("b", "raw-b"), nickname: "Sökmodell", provider_type: "azure_openai" }
      ]}
      value="a"
      onChange={() => {}}
    />
  );
  const select = screen.getByRole("combobox", { name: "Embedding-modell" });
  expect(select.textContent).toContain("Sökmodell (Berget)");
  fireEvent.keyDown(select, { key: "ArrowDown" });
  expect(await screen.findByRole("option", { name: "Sökmodell (Azure Openai)" })).toBeTruthy();
});
