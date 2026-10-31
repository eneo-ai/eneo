// @vitest-environment jsdom
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { AssistantContextMeter } from "./assistant-context-meter";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
afterEach(() => {
  cleanup();
  api.POST.mockReset();
});
const props = {
  assistantId: "assistant",
  model: { id: "model-a", token_limit: 1000 },
  modelConfirmed: true,
  prompt: "Live draft",
  attachments: [
    { id: "lookup", inline_text: false },
    { id: "inline", inline_text: true }
  ]
};
const response = {
  data: {
    prompt_tokens: 500,
    file_tokens: 200,
    skill_context_tokens: 100,
    context_reserve_tokens: 200
  },
  response: new Response("{}")
};
it("uses authoritative totals once, per-file modes and the reserve-adjusted ceiling", async () => {
  api.POST.mockResolvedValue(response);
  const view = renderInApp(<AssistantContextMeter {...props} />);
  const budget = await screen.findByRole("button", { name: /Kontextbudget: ~700/ });
  expect(budget.className).toContain("text-warning");
  expect(api.POST).toHaveBeenCalledWith(
    "/api/v1/conversations/preflight",
    expect.objectContaining({
      body: {
        assistant_id: "assistant",
        question: "",
        file_ids: [],
        assistant_prompt: "Live draft",
        attachments: props.attachments
      },
      signal: expect.any(AbortSignal)
    })
  );
  api.POST.mockResolvedValue({ ...response, data: { ...response.data, prompt_tokens: 650 } });
  view.rerender(<AssistantContextMeter {...props} prompt="Larger live draft" />);
  expect(screen.queryByRole("button", { name: /Kontextbudget:/ })).toBeNull();
  expect((await screen.findByRole("button", { name: /Kontextbudget: ~850/ })).className).toContain(
    "text-destructive"
  );
  expect(screen.getByText(/annars går assistenten inte att spara/)).toBeTruthy();
});
it("cancels obsolete model inputs and hides failures without keeping an old estimate", async () => {
  let resolve!: (value: typeof response) => void;
  api.POST.mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      })
  );
  const view = renderInApp(<AssistantContextMeter {...props} />);
  await waitFor(() => expect(api.POST).toHaveBeenCalledOnce());
  const signal = api.POST.mock.calls[0]![1].signal as AbortSignal;
  view.rerender(
    <AssistantContextMeter
      {...props}
      model={{ id: "model-b", token_limit: 500 }}
      modelConfirmed={false}
    />
  );
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(response));
  expect(screen.queryByRole("button", { name: /Kontextbudget:/ })).toBeNull();
  api.POST.mockRejectedValue(new Error("advisory failure"));
  view.rerender(<AssistantContextMeter {...props} model={{ id: "model-b", token_limit: 500 }} />);
  expect(await screen.findByText(/Kontexten kunde inte uppskattas/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Kontextbudget:/ })).toBeNull();
});
