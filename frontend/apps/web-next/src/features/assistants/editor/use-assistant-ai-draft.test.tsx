// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import { assistantQueryOptions, type Assistant } from "./use-assistant";
import { useAssistantAiDraft } from "./use-assistant-ai-draft";
import { AssistantContextMeter } from "./assistant-context-meter";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
const catalog = vi.hoisted(() =>
  ["a", "b", "c"].map((id) => ({
    id,
    name: id,
    token_limit: 1000,
    supports_tool_calling: true,
    supported_model_kwargs: { temperature: { supported: true } }
  }))
);
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({ routeId: "space", space: { completion_models: catalog } })
}));
afterEach(() => {
  cleanup();
  api.POST.mockReset();
});
const initial = {
  id: "assistant",
  completion_model: catalog[0],
  completion_model_kwargs: { temperature: 1 }
} as unknown as Assistant;
function show(assistant = initial, meter = false) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", "assistant"], assistant);
  function Page() {
    const { data } = useSuspenseQuery(assistantQueryOptions(api as never, "assistant"));
    const draft = useAssistantAiDraft(data);
    return (
      <>
        <output>
          {draft.modelId}:{draft.kwargs.temperature}:{String(draft.confirmed)}:
          {draft.effectiveModel?.id}
        </output>
        <button onClick={() => draft.changeModel("b")}>B</button>
        <button onClick={() => void draft.persist(draft.modelId, draft.kwargs)}>Retry model</button>
        {draft.isError && <p>Model save failed</p>}
        {meter && (
          <AssistantContextMeter
            assistantId={data.id}
            model={draft.effectiveModel}
            modelConfirmed={draft.confirmed}
            prompt="Live draft"
            attachments={[]}
          />
        )}
      </>
    );
  }
  renderInApp(<Page />, { queryClient });
  return queryClient;
}
it("cancels an in-flight preflight during model change, keeps a failed draft and confirms after retry", async () => {
  let resolveOld!: (response: unknown) => void;
  let preflights = 0;
  let saves = 0;
  api.POST.mockImplementation(async (path, init) => {
    if (path === "/api/v1/conversations/preflight") {
      if (preflights++ === 0)
        return new Promise((resolve) => {
          resolveOld = resolve;
        });
      return {
        data: { file_tokens: 0, prompt_tokens: 200, context_reserve_tokens: 0 },
        response: new Response("{}")
      };
    }
    if (saves++ === 0) throw new Error("failed");
    return {
      data: {
        ...initial,
        completion_model: catalog[1],
        completion_model_kwargs: init.body.completion_model_kwargs
      },
      response: new Response("{}")
    };
  });
  show(initial, true);
  await waitFor(() => expect(preflights).toBe(1));
  const oldSignal = api.POST.mock.calls[0]![1].signal as AbortSignal;
  fireEvent.click(screen.getByRole("button", { name: "B" }));
  expect(await screen.findByText("b:1:false:b")).toBeTruthy();
  await screen.findByText("Model save failed");
  expect(oldSignal.aborted).toBe(true);
  await act(async () =>
    resolveOld({
      data: { file_tokens: 0, prompt_tokens: 900, context_reserve_tokens: 0 },
      response: new Response("{}")
    })
  );
  expect(screen.queryByRole("button", { name: /Kontextbudget:/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Retry model" }));
  expect(await screen.findByText("b:1:true:b")).toBeTruthy();
  expect(api.POST).toHaveBeenCalledWith(
    "/api/v1/assistants/{id}/",
    expect.objectContaining({
      body: { completion_model: { id: "b" }, completion_model_kwargs: { temperature: 1 } }
    })
  );
  expect(await screen.findByRole("button", { name: /Kontextbudget: ~200/ })).toBeTruthy();
});
it("adopts an external model and its parameters together when the draft is unchanged", async () => {
  const queryClient = show();
  act(() =>
    queryClient.setQueryData(["assistants", "assistant"], {
      ...initial,
      completion_model: catalog[2],
      completion_model_kwargs: { temperature: 0.25 }
    })
  );
  expect(await screen.findByText("c:0.25:true:c")).toBeTruthy();
});
it("uses the governance-locked model for material even when the stored pick differs", () => {
  show({
    ...initial,
    effective_config: { models_enforced: true, locked_model: catalog[2], available_models: catalog }
  } as unknown as Assistant);
  expect(screen.getByText("a:1:true:c")).toBeTruthy();
});
