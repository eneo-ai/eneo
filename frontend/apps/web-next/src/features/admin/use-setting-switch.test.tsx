// @vitest-environment jsdom
import { act, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { router } from "@/test/navigation";
import { renderHookInApp, testQueryClient } from "@/test/render";

const toastApiError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/toast", () => ({ toastApiError }));
vi.mock("next/navigation", () => import("@/test/navigation"));

import { useSettingSwitch, type SettingSwitchOptions } from "./use-setting-switch";

afterEach(() => vi.clearAllMocks());

function deferred() {
  let settle: { resolve: () => void; reject: (error: unknown) => void } = {
    resolve: () => {},
    reject: () => {}
  };
  const promise = new Promise<void>((resolve, reject) => {
    settle = { resolve: () => resolve(), reject };
  });
  return { promise, ...settle };
}

/** The hook with the server's value in `server.saved`; rerender after changing it. */
function render(
  initial: boolean,
  save: (enabled: boolean) => Promise<unknown>,
  options?: SettingSwitchOptions
) {
  const server = { saved: initial };
  const rendered = renderHookInApp(() => useSettingSwitch("setting", server.saved, save, options));
  return { ...rendered, server };
}

it("shows a press at once, says it is saving, and keeps it once saved", async () => {
  const save = deferred();
  const { result } = render(false, () => save.promise);

  act(() => result.current[1](true));
  await waitFor(() => expect(result.current[0]).toBe(true));
  expect(result.current[2]).toBe(true);

  await act(async () => save.resolve());
  expect(result.current).toEqual([true, expect.any(Function), false]);
  // A tenant setting refreshes the server layout by default.
  expect(router.refresh).toHaveBeenCalledTimes(1);
});

it("refreshes a query-backed setting its own way, and follows the server's value", async () => {
  const onSaved = vi.fn();
  const { result, rerender, server } = render(false, () => Promise.resolve(), { onSaved });

  act(() => result.current[1](true));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(true));
  expect(router.refresh).not.toHaveBeenCalled();
  expect(result.current[0]).toBe(true);

  // The refetch brings the saved value, then a change made elsewhere (another
  // screen, a category cascading to its actions): the switch follows.
  server.saved = true;
  rerender();
  expect(result.current[0]).toBe(true);
  server.saved = false;
  rerender();
  expect(result.current[0]).toBe(false);
});

it("falls back to the saved value and reports a failed save its own way", async () => {
  const onError = vi.fn();
  const failure = new Error("nope");
  const save = deferred();
  const { result } = render(true, () => save.promise, { onError });

  act(() => result.current[1](false));
  await waitFor(() => expect(result.current[0]).toBe(false));

  await act(async () => save.reject(failure));
  await waitFor(() => expect(onError).toHaveBeenCalledWith(failure));
  expect(result.current[0]).toBe(true);
  expect(toastApiError).not.toHaveBeenCalled();
});

it("queues saves that share a queue behind each other", async () => {
  const first = deferred();
  const second = vi.fn(() => Promise.resolve());
  const queryClient = testQueryClient();
  const a = renderHookInApp(
    () => useSettingSwitch("a", false, () => first.promise, { onSaved: () => {}, queue: "shared" }),
    { queryClient }
  );
  const b = renderHookInApp(
    () => useSettingSwitch("b", false, second, { onSaved: () => {}, queue: "shared" }),
    { queryClient }
  );

  act(() => a.result.current[1](true));
  await waitFor(() => expect(a.result.current[2]).toBe(true));
  act(() => b.result.current[1](true));
  await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
  expect(second).not.toHaveBeenCalled();

  await act(async () => first.resolve());
  await waitFor(() => expect(second).toHaveBeenCalledTimes(1));
});
