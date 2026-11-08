import { expect, it } from "vitest";
import { embeddingModelGroupTitle, embeddingModelLabel } from "./embedding-model-label";
import type { EmbeddingModel } from "./knowledge";
const model: EmbeddingModel = {
  id: "m",
  name: "raw",
  nickname: "Sökmodell",
  is_deprecated: false,
  open_source: false,
  provider_name: "Berget"
};
it("uses a hosting provider and nickname independently from availability", () => {
  expect(embeddingModelLabel(model)).toBe("Sökmodell (Berget)");
  expect(embeddingModelGroupTitle({ ...model, is_org_enabled: false }, false, (key) => key)).toBe(
    "Sökmodell (Berget) (embedding_model_disabled_by_admin)"
  );
  expect(embeddingModelGroupTitle({ ...model, is_org_enabled: true }, false, (key) => key)).toBe(
    "Sökmodell (Berget) (embedding_model_not_in_space)"
  );
  expect(embeddingModelGroupTitle(model, false, (key) => key)).toBe(
    "Sökmodell (Berget) (disabled)"
  );
  expect(embeddingModelGroupTitle(model, true, (key) => key)).toBe("Sökmodell (Berget)");
});
