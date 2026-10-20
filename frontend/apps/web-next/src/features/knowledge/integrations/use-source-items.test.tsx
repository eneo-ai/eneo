// @vitest-environment jsdom
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import { act, cleanup, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";
import type { IntegrationKnowledge } from "../knowledge";
import { renderHookInApp, testQueryClient } from "@/test/render";
import { useSourceItems } from "./use-source-items";

const key = ["spaces", "space-1"];
const item = makeIntegration({ id: "i1" }) as IntegrationKnowledge;
afterEach(cleanup);

it.each([-300_000, 300_000])(
  "trusts a successful reread regardless of a %i ms clock offset",
  async (offset) => {
    const queryClient = testQueryClient();
    queryClient.setQueryData(key, makeSpace(), { updatedAt: Date.now() + offset });
    const read = vi.fn(async () => makeSpace());
    const { result, rerender } = renderHookInApp(
      () => {
        const { data } = useQuery({ queryKey: key, queryFn: read, staleTime: Infinity });
        return useSourceItems("space-1", data?.knowledge.integration_knowledge_list.items ?? [], {
          items: [item]
        });
      },
      { queryClient }
    );
    expect(result.current).toEqual([item]);
    await waitFor(() => expect(result.current).toEqual([]));
    rerender();
    expect(result.current).toEqual([]);
    expect(read).toHaveBeenCalledTimes(1);
  }
);

it("keeps the server copy through a failed read, then accepts a successful empty response", async () => {
  const queryClient = testQueryClient();
  queryClient.setQueryData(key, makeSpace());
  const read = vi.fn(async () => makeSpace()).mockRejectedValueOnce(new Error("offline"));
  const { result } = renderHookInApp(
    () => {
      const { data } = useQuery({ queryKey: key, queryFn: read, staleTime: Infinity });
      return useSourceItems("space-1", data?.knowledge.integration_knowledge_list.items ?? [], {
        items: [item]
      });
    },
    { queryClient }
  );
  await waitFor(() => expect(queryClient.getQueryState(key)?.status).toBe("error"));
  expect(result.current).toEqual([item]);
  await act(() => queryClient.invalidateQueries({ queryKey: key }));
  await waitFor(() => expect(result.current).toEqual([]));
});

it("keeps the server item during hydration until the client reread completes", async () => {
  const serverClient = testQueryClient();
  const browserClient = testQueryClient();
  serverClient.setQueryData(key, makeSpace());
  browserClient.setQueryData(key, makeSpace());
  browserClient.setQueryData(key, makeSpace());
  let finish = () => {};
  const response = new Promise<ReturnType<typeof makeSpace>>((resolve) => {
    finish = () => resolve(makeSpace());
  });
  function Source() {
    const { data } = useQuery({ queryKey: key, queryFn: () => response, staleTime: Infinity });
    const items = useSourceItems(
      "space-1",
      data?.knowledge.integration_knowledge_list.items ?? [],
      { items: [item] }
    );
    return <div>{items.map((entry) => entry.id).join(",") || "empty"}</div>;
  }
  const container = document.createElement("div");
  container.innerHTML = renderToString(
    <QueryClientProvider client={serverClient}>
      <Source />
    </QueryClientProvider>
  );
  expect(container.textContent).toBe("i1");
  const root = hydrateRoot(
    container,
    <QueryClientProvider client={browserClient}>
      <Source />
    </QueryClientProvider>
  );
  try {
    await act(async () => {});
    expect(container.textContent).toBe("i1");
    await act(async () => {
      finish();
    });
    await waitFor(() => expect(container.textContent).toBe("empty"));
  } finally {
    await act(async () => root.unmount());
    serverClient.clear();
    browserClient.clear();
  }
});
