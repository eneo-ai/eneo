// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useSuspenseQuery } from "@tanstack/react-query";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { assistantQueryOptions, type Assistant } from "./use-assistant";
import { MaterialHandling } from "./material-handling";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/features/spaces/use-space", () => ({ useSpace: () => ({ routeId: "space" }) }));
afterEach(() => {
  cleanup();
  api.POST.mockReset();
});
const initial = { id: "assistant", knowledge_mode: "tool", inline_file_text: false } as Assistant;
function show(references = true, supportsTools = true) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", "assistant"], initial);
  function Page() {
    const { data } = useSuspenseQuery(assistantQueryOptions(api as never, "assistant"));
    return <MaterialHandling assistant={data} modelSupportsTools={supportsTools} />;
  }
  renderInApp(<Page />, {
    queryClient,
    appContext: testAppContext({ settings: { file_references_enabled: references } })
  });
}
it("shows persisted modes and retries a failed change through assistant autosave", async () => {
  api.POST.mockRejectedValueOnce(new Error("failed")).mockImplementation(async (_path, init) => ({
    data: { ...initial, ...init.body },
    response: new Response("{}")
  }));
  show();
  expect((screen.getByRole("radio", { name: "Vid behov" }) as HTMLInputElement).checked).toBe(true);
  fireEvent.click(screen.getByRole("radio", { name: "Inför varje svar" }));
  fireEvent.click(await screen.findByRole("button", { name: "Försök igen" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
  expect(api.POST).toHaveBeenLastCalledWith(
    "/api/v1/assistants/{id}/",
    expect.objectContaining({ body: { knowledge_mode: "inject" } })
  );
  fireEvent.click(screen.getByRole("radio", { name: "Läs in direkt" }));
  await waitFor(() =>
    expect(api.POST).toHaveBeenLastCalledWith(
      "/api/v1/assistants/{id}/",
      expect.objectContaining({ body: { inline_file_text: true } })
    )
  );
});
it("explains unavailable file references and the tool-model fallback", () => {
  show(false, false);
  expect(screen.getByText(/Kunskapskällor söks därför inför varje svar/)).toBeTruthy();
  expect(screen.getByText(/Filåtkomst vid behov är inte tillgänglig/)).toBeTruthy();
  expect(screen.queryByRole("radio", { name: "Öppna vid behov" })).toBeNull();
});
