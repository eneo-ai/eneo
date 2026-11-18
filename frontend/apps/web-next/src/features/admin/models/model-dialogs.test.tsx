// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ModelSelection } from "./model-dialogs";

const remove = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: { DELETE: remove } }));
vi.mock("@/lib/toast", () => ({ toast }));
vi.mock("use-intl", () => ({ useTranslations: () => (key: string) => key }));

import { ModelDialogs } from "./model-dialogs";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("offers a migration from a refused delete of a model in use, with its support references", async () => {
  remove.mockResolvedValue({
    error: { message: "Model in use", eneo_error_code: 9039, error_id: "error-1" },
    response: new Response("{}", { status: 409, headers: { "x-trace-id": "trace-1" } })
  });
  const onMigrate = vi.fn();
  const selection = {
    model: { id: "model-1", name: "gpt-4o" },
    kind: "completion",
    action: "delete"
  } as unknown as ModelSelection;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ModelDialogs
        selection={selection}
        classifications={[]}
        securityEnabled={false}
        onClose={() => {}}
        onMigrate={onMigrate}
        onEdit={() => {}}
      />
    </QueryClientProvider>
  );

  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "delete" }));

  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith("eneo_error_9039", {
      description: "error_id: error-1 · trace_id: trace-1",
      action: { label: "migrate", onClick: expect.any(Function) }
    })
  );
  const [, options] = toast.error.mock.calls[0] as [string, { action: { onClick: () => void } }];
  options.action.onClick();
  expect(onMigrate).toHaveBeenCalledTimes(1);
});
