// @vitest-environment jsdom
import { QueryClient, QueryClientProvider, useMutation } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import type { Assistant } from "./use-assistant";

const update = vi.hoisted(() => vi.fn().mockResolvedValue({}));
const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("./use-assistant", () => ({
  useUpdateAssistant: () => useMutation({ mutationFn: (body: unknown) => update(body) })
}));
vi.mock("@/features/spaces/use-space", () => ({ useSpace: () => ({ space: { id: "space-1" } }) }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/components/composites/use-autosave", () => ({
  useAutosave: () => (operation: () => Promise<unknown>) => operation()
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

import { RerankerRow } from "./reranker-row";

const rerankModel = (id: string, overrides: Record<string, unknown> = {}) => ({
  id,
  name: id,
  nickname: `Reranker ${id}`,
  can_access: true,
  meets_security_classification: true,
  ...overrides
});

afterEach(() => {
  cleanup();
  update.mockReset();
  update.mockResolvedValue({});
});

function show(rerankModelId: string | null, rerankModels: unknown[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const models = { rerank_models: rerankModels };
  client.setQueryData(["ai-models", "space-1"], models);
  api.GET.mockResolvedValue({ data: models, response: new Response("{}") });
  render(
    <QueryClientProvider client={client}>
      <RerankerRow assistant={{ id: "assistant", rerank_model_id: rerankModelId } as Assistant} />
    </QueryClientProvider>
  );
}

function open() {
  const select = screen.getByRole("combobox", { name: "material_reranker" });
  fireEvent.keyDown(select, { key: "Enter" });
  return select;
}

describe("result ranking", () => {
  it("offers only the rerank models the space allows and saves the choice", async () => {
    show(null, [
      rerankModel("a"),
      rerankModel("disabled", { can_access: false }),
      rerankModel("too-low", { meets_security_classification: false })
    ]);
    expect(open().textContent).toContain("material_reranker_none");
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "material_reranker_none",
      "Reranker a"
    ]);

    fireEvent.click(screen.getByRole("option", { name: "Reranker a" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith({ rerank_model_id: "a" }));
  });

  it("clears the choice with no reranking", async () => {
    show("a", [rerankModel("a")]);
    expect(open().textContent).toContain("Reranker a");
    fireEvent.click(await screen.findByRole("option", { name: "material_reranker_none" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith({ rerank_model_id: null }));
  });

  it("is not shown without selectable models or a saved choice", () => {
    show(null, [rerankModel("disabled", { can_access: false })]);
    expect(screen.queryByRole("combobox", { name: "material_reranker" })).toBeNull();
  });

  it("does not call a saved choice unavailable while the models load", () => {
    api.GET.mockReturnValue(new Promise(() => {}));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RerankerRow assistant={{ id: "assistant", rerank_model_id: "a" } as Assistant} />
      </QueryClientProvider>
    );
    expect(screen.queryByText("material_reranker_unavailable")).toBeNull();
  });

  it("keeps a saved choice that is no longer available, with a warning", async () => {
    show("gone", [rerankModel("a")]);
    const select = screen.getByRole("combobox", { name: "material_reranker" });
    expect(select.textContent).toContain("material_reranker_missing");
    const warning = screen.getByText("material_reranker_unavailable");
    expect(within(document.body).getByText("material_reranker_description")).toBeTruthy();
    expect(warning).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });
});
