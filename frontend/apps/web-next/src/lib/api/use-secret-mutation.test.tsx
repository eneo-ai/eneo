// @vitest-environment jsdom
import { act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { cachedText, renderHookInApp } from "@/test/render";
import { useSecretMutation } from "./use-secret-mutation";

const SECRET = "sk-synthetic-secret-1234";
type Body = { name: string; api_key: string };
const body: Body = { name: "Leverantör", api_key: SECRET };
const saved = { id: "p1", name: "Leverantör" };

describe("useSecretMutation", () => {
  it("hands the variables to the call and its callbacks, and none to the cache", async () => {
    const mutationFn = vi.fn((sent: Body) => Promise.resolve({ ...saved, name: sent.name }));
    const onMutate = vi.fn();
    const onSuccess = vi.fn();
    const onSettled = vi.fn();
    const { result, queryClient } = renderHookInApp(() =>
      useSecretMutation({ mutationFn, onMutate, onSuccess, onSettled })
    );

    act(() => result.current.mutate(body));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mutationFn).toHaveBeenCalledWith(body, expect.anything());
    expect(onMutate).toHaveBeenCalledWith(body, expect.anything());
    expect(onSuccess).toHaveBeenCalledWith(saved, body, undefined, expect.anything());
    expect(onSettled).toHaveBeenCalledWith(saved, null, body, undefined, expect.anything());
    expect(result.current.data).toEqual(saved);
    expect(cachedText(queryClient)).not.toContain(SECRET);

    // The next call has its own variables.
    const next = { name: "Annan", api_key: "sk-synthetic-other-5678" };
    act(() => result.current.mutate(next));
    await waitFor(() => expect(mutationFn).toHaveBeenCalledTimes(2));
    expect(mutationFn).toHaveBeenLastCalledWith(next, expect.anything());
    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(2));
    expect(cachedText(queryClient)).not.toContain("sk-synthetic-other-5678");
  });

  it("hands a failure its variables, and none to the cache", async () => {
    const failure = new Error("Refused");
    const onError = vi.fn();
    const onSettled = vi.fn();
    const { result, queryClient } = renderHookInApp(() =>
      useSecretMutation<never, Error, Body>({
        mutationFn: () => Promise.reject(failure),
        onError,
        onSettled
      })
    );

    act(() => result.current.mutate(body));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(onError).toHaveBeenCalledWith(failure, body, undefined, expect.anything());
    expect(onSettled).toHaveBeenCalledWith(undefined, failure, body, undefined, expect.anything());
    expect(result.current.error).toBe(failure);
    expect(cachedText(queryClient)).not.toContain(SECRET);
  });

  it("is pending while the call runs, and mutateAsync resolves with its data", async () => {
    let finish: (data: string) => void = () => {};
    const { result, queryClient } = renderHookInApp(() =>
      useSecretMutation<string, Error, Body>({
        mutationFn: () => new Promise<string>((resolve) => (finish = resolve))
      })
    );

    let answer: Promise<string> = Promise.resolve("");
    act(() => {
      answer = result.current.mutateAsync(body);
    });

    await waitFor(() => expect(result.current.isPending).toBe(true));
    expect(cachedText(queryClient)).not.toContain(SECRET);
    await act(async () => finish("saved"));
    await expect(answer).resolves.toBe("saved");
    expect(cachedText(queryClient)).not.toContain(SECRET);
  });
});
