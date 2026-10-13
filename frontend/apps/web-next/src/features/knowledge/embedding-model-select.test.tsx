// @vitest-environment jsdom
import { screen } from "@testing-library/react";
import { expect, it } from "vitest";
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
