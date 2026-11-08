// @vitest-environment jsdom
import { keepPreviousData, onlineManager, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { cursorPagination, flattenPages } from "@/lib/api/pagination";
import {
  ListError,
  LoadMore,
  QueryStateBoundary,
  blockingError,
  type QueryLike
} from "./query-state";

afterEach(cleanup);

function query<T>(overrides: Partial<QueryLike<T>>): QueryLike<T> {
  return {
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    isFetching: false,
    errorUpdatedAt: 0,
    dataUpdatedAt: 0,
    refetch: vi.fn(),
    ...overrides
  };
}

describe("QueryStateBoundary", () => {
  it("shows skeleton rows in a busy status region while the query is pending", () => {
    renderInApp(
      <QueryStateBoundary query={query<string[]>({ isPending: true })} rows={2}>
        {(items) => (
          <ul>
            {items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
      </QueryStateBoundary>
    );
    const region = screen.getByRole("status");
    expect(region.getAttribute("aria-busy")).toBe("true");
    expect(within(region).getByText("Laddar...")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("shows the catalog's message, retries the failed query and keeps the code behind details", async () => {
    const refetch = vi.fn();
    const error = new EneoApiError("Internal server error", {
      status: 500,
      code: 9024,
      traceId: "trace-123"
    });
    const { container } = renderInApp(
      <QueryStateBoundary query={query<string[]>({ isError: true, error, refetch })}>
        {() => <ul />}
      </QueryStateBoundary>
    );

    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("Innehållet kunde inte hämtas")).toBeTruthy();
    // 9024 → the catalog's INTERNAL_SERVER_ERROR text, not the backend's English message.
    expect(alert.textContent).not.toContain("Internal server error");
    expect(within(alert).getByText(/gick fel|Ett internt fel|fel/i)).toBeTruthy();
    expect(screen.queryByText("HTTP-status: 500")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Expandera" }));
    expect(screen.getByText("HTTP-status: 500")).toBeTruthy();
    expect(screen.getByText("Felkod: 9024")).toBeTruthy();
    expect(screen.getByText("Spårnings-ID: trace-123")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(refetch).toHaveBeenCalledTimes(1);
    await expectNoAxeViolations(container);
  });

  it("retries only the queries that failed when several are combined", () => {
    const failedRefetch = vi.fn();
    const okRefetch = vi.fn();
    renderInApp(
      <QueryStateBoundary
        queries={[
          query({ isError: true, error: new Error("boom"), refetch: failedRefetch }),
          query({ data: [], refetch: okRefetch })
        ]}
      >
        {() => <ul />}
      </QueryStateBoundary>
    );
    expect(screen.getByText("Något gick fel. Försök igen.")).toBeTruthy();
    // A plain Error has no status or code, so there is nothing to disclose.
    expect(screen.queryByRole("button", { name: "Expandera" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(failedRefetch).toHaveBeenCalledTimes(1);
    expect(okRefetch).not.toHaveBeenCalled();
  });

  it("ignores a second press while the retry is in flight", () => {
    const refetch = vi.fn();
    renderInApp(
      <ListError error={new Error("boom")} onRetry={refetch} isRetrying title="Listan är trasig" />
    );
    expect(screen.getByText("Listan är trasig")).toBeTruthy();
    const retry = screen.getByRole("button", { name: /Försök igen/ });
    expect(retry.getAttribute("aria-busy")).toBe("true");
    expect(retry.hasAttribute("disabled")).toBe(false);
    fireEvent.click(retry);
    expect(refetch).not.toHaveBeenCalled();
  });

  it("renders the content with the data once loaded", () => {
    renderInApp(
      <QueryStateBoundary query={query<string[]>({ data: ["Anna", "Bo"] })}>
        {(items) => (
          <ul>
            {items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
      </QueryStateBoundary>
    );
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Anna", "Bo"]);
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("ListError", () => {
  it("shows the backend error id and the trace id under their labels", () => {
    const error = new EneoApiError("An unexpected error occurred.", {
      status: 500,
      errorId: "8bc91e0a",
      traceId: "trace-123"
    });
    renderInApp(<ListError error={error} onRetry={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Expandera" }));
    expect(screen.getByText("Fel-ID: 8bc91e0a")).toBeTruthy();
    expect(screen.getByText("Spårnings-ID: trace-123")).toBeTruthy();
  });

  it("shows no reference labels when the error carries no ids", () => {
    renderInApp(<ListError error={new EneoApiError("Gone", { status: 404 })} onRetry={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Expandera" }));
    expect(screen.queryByText(/Fel-ID|Spårnings-ID/)).toBeNull();
  });

  it("names each retry after its section when the error has a title", () => {
    const retryModels = vi.fn();
    renderInApp(
      <>
        <ListError error={new Error("boom")} title="Modeller" onRetry={retryModels} />
        <ListError error={new Error("boom")} title="MCP-servrar" onRetry={vi.fn()} />
      </>
    );

    fireEvent.click(screen.getByRole("button", { name: "Försök igen: Modeller" }));
    expect(retryModels).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Försök igen: MCP-servrar" })).toBeTruthy();
  });

  it("offers no retry when there is nothing to run again", () => {
    renderInApp(<ListError error={new Error("boom")} title="Kunde inte spara" />);

    expect(within(screen.getByRole("alert")).getByText("Kunde inte spara")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Försök igen" })).toBeNull();
  });

  it("puts the message in the title when compact", () => {
    renderInApp(<ListError error={new Error("boom")} onRetry={vi.fn()} compact />);

    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("Något gick fel. Försök igen.")).toBeTruthy();
    expect(within(alert).queryByText("Innehållet kunde inte hämtas")).toBeNull();
  });
});

describe("query failure with data on screen", () => {
  const names = (items: string[]) => (
    <ul>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );

  it("keeps the content when a refetch fails and shows the error with a retry above it", () => {
    const refetch = vi.fn();
    renderInApp(
      <QueryStateBoundary
        query={query<string[]>({
          data: ["Anna", "Bo"],
          isError: true,
          error: new Error("boom"),
          dataUpdatedAt: 1,
          errorUpdatedAt: 2,
          refetch
        })}
      >
        {names}
      </QueryStateBoundary>
    );

    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Anna", "Bo"]);
    const title = screen.getByText(
      "Innehållet kunde inte uppdateras. Senast hämtade uppgifter visas."
    );
    expect(title.closest('[role="alert"]')).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Försök igen/ }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("replaces the content with the error when there is nothing to show", () => {
    renderInApp(
      <QueryStateBoundary
        query={query<string[]>({ isError: true, error: new Error("boom"), errorUpdatedAt: 2 })}
      >
        {names}
      </QueryStateBoundary>
    );
    expect(screen.getByText("Innehållet kunde inte hämtas")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("keeps the retry button, not a skeleton, while a failure without data is retried", () => {
    // React Query reports a retry without data as pending and clears isError.
    renderInApp(
      <QueryStateBoundary
        query={query<string[]>({ isPending: true, isFetching: true, errorUpdatedAt: 2 })}
      >
        {names}
      </QueryStateBoundary>
    );
    const retry = screen.getByRole("button", { name: /^Försök igen/ });
    expect(retry.getAttribute("aria-busy")).toBe("true");
    expect(screen.queryByText("Laddar...")).toBeNull();
  });

  it("keeps the focused retry button while an offline retry waits for the network", async () => {
    function Names() {
      const list = useQuery({
        queryKey: ["names-offline"],
        queryFn: async (): Promise<string[]> => {
          throw new Error("boom");
        }
      });
      return <QueryStateBoundary query={list}>{names}</QueryStateBoundary>;
    }
    renderInApp(<Names />);
    const retry = await screen.findByRole("button", { name: /^Försök igen/ });
    retry.focus();

    onlineManager.setOnline(false);
    try {
      fireEvent.click(retry);
      // The paused retry is neither fetching nor failed: still no skeleton.
      await waitFor(() => expect(screen.queryByText("Laddar...")).toBeNull());
      expect(retry.isConnected).toBe(true);
      expect(document.activeElement).toBe(retry);
    } finally {
      onlineManager.setOnline(true);
    }
  });

  it("decides blocking from data, not from the error flag alone", () => {
    expect(blockingError(query({ isError: true, errorUpdatedAt: 2 }))).toBe(true);
    // A retry of a failure without data: pending, fetching or paused offline.
    expect(blockingError(query({ isPending: true, isFetching: true, errorUpdatedAt: 2 }))).toBe(
      true
    );
    expect(blockingError(query({ isPending: true, errorUpdatedAt: 2 }))).toBe(true);
    expect(
      blockingError(query({ data: [], isError: true, dataUpdatedAt: 1, errorUpdatedAt: 2 }))
    ).toBe(false);
    expect(blockingError(query({ isPending: true, isFetching: true }))).toBe(false);
  });
});

describe("LoadMore", () => {
  function Names({ fetchPage }: { fetchPage: (cursor: string | undefined) => Promise<unknown> }) {
    const list = useInfiniteQuery({
      ...cursorPagination,
      queryKey: ["names"],
      queryFn: ({ pageParam }) =>
        fetchPage(pageParam) as Promise<{
          items: string[];
          total_count: number;
          next_cursor: string | null;
        }>
    });
    return (
      <QueryStateBoundary query={list}>
        {(data) => (
          <>
            {names(flattenPages(data.pages))}
            <LoadMore query={list} label="Visa fler" />
          </>
        )}
      </QueryStateBoundary>
    );
  }
  const names = (items: string[]) => (
    <ul>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );

  it("keeps the loaded rows when the next page fails and retries only that page", async () => {
    let failSecond = true;
    const fetchPage = vi.fn(async (cursor: string | undefined) => {
      if (!cursor) return { items: ["Anna"], total_count: 2, next_cursor: "page-2" };
      if (failSecond) throw new Error("boom");
      return { items: ["Bo"], total_count: 2, next_cursor: null };
    });
    renderInApp(<Names fetchPage={fetchPage} />);

    fireEvent.click(await screen.findByRole("button", { name: "Visa fler" }));
    const title = await screen.findByText("Det gick inte att läsa in fler.");
    expect(title.closest('[role="alert"]')).not.toBeNull();
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Anna"]);
    // The boundary leaves a next-page failure to LoadMore: one error, not two.
    expect(screen.queryByText(/kunde inte uppdateras/)).toBeNull();

    failSecond = false;
    fetchPage.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /^Försök igen/ }));
    await waitFor(() =>
      expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
        "Anna",
        "Bo"
      ])
    );
    expect(fetchPage).toHaveBeenCalledTimes(1);
    expect(fetchPage).toHaveBeenCalledWith("page-2");
    expect(screen.queryByText("Det gick inte att läsa in fler.")).toBeNull();
  });

  it("does not call a refresh failure a failed next page while the next page loads", async () => {
    let phase: "ok" | "refresh-fails" | "next-pending" = "ok";
    const fetchPage = vi.fn(async (cursor: string | undefined) => {
      if (!cursor) {
        if (phase === "refresh-fails") throw new Error("refresh failed");
        return { items: ["Anna"], total_count: 2, next_cursor: "page-2" };
      }
      return new Promise(() => {});
    });
    const { queryClient } = renderInApp(<Names fetchPage={fetchPage} />);
    await screen.findByText("Anna");

    phase = "refresh-fails";
    await queryClient.refetchQueries({ queryKey: ["names"] });
    expect(await screen.findByText(/kunde inte uppdateras/)).toBeTruthy();

    phase = "next-pending";
    fireEvent.click(screen.getByRole("button", { name: "Visa fler" }));
    await waitFor(() => expect(fetchPage).toHaveBeenLastCalledWith("page-2"));
    expect(screen.queryByText("Det gick inte att läsa in fler.")).toBeNull();
    expect(screen.getByText(/kunde inte uppdateras/)).toBeTruthy();
  });

  it("keeps a failed next page's error and focused retry while a refresh runs", async () => {
    let phase: "ok" | "next-fails" | "refresh-pending" = "ok";
    const fetchPage = vi.fn(async (cursor: string | undefined) => {
      if (!cursor) {
        if (phase === "refresh-pending") return new Promise(() => {});
        return { items: ["Anna"], total_count: 2, next_cursor: "page-2" };
      }
      throw new Error("boom");
    });
    const { queryClient } = renderInApp(<Names fetchPage={fetchPage} />);

    phase = "next-fails";
    fireEvent.click(await screen.findByRole("button", { name: "Visa fler" }));
    await screen.findByText("Det gick inte att läsa in fler.");
    const retry = screen.getByRole("button", { name: /^Försök igen/ });
    retry.focus();

    phase = "refresh-pending";
    void queryClient.refetchQueries({ queryKey: ["names"] });
    await waitFor(() => expect(fetchPage).toHaveBeenLastCalledWith(undefined));
    expect(screen.getByText("Det gick inte att läsa in fler.")).toBeTruthy();
    expect(screen.queryByText(/kunde inte uppdateras/)).toBeNull();
    expect(retry.isConnected).toBe(true);
    expect(document.activeElement).toBe(retry);
  });

  it("keeps a failed next page's error through a refresh paused offline", async () => {
    let phase: "ok" | "next-fails" | "recovered" = "ok";
    const fetchPage = vi.fn(async (cursor: string | undefined) => {
      if (!cursor) return { items: ["Anna"], total_count: 2, next_cursor: "page-2" };
      if (phase === "next-fails") throw new Error("boom");
      return { items: ["Bo"], total_count: 2, next_cursor: null };
    });
    const { queryClient } = renderInApp(<Names fetchPage={fetchPage} />);

    phase = "next-fails";
    fireEvent.click(await screen.findByRole("button", { name: "Visa fler" }));
    await screen.findByText("Det gick inte att läsa in fler.");
    const retry = screen.getByRole("button", { name: /^Försök igen/ });
    retry.focus();

    onlineManager.setOnline(false);
    try {
      void queryClient.refetchQueries({ queryKey: ["names"] });
      await waitFor(() => expect(queryClient.getQueryState(["names"])?.fetchStatus).toBe("paused"));
      expect(screen.getByText("Det gick inte att läsa in fler.")).toBeTruthy();
      expect(screen.queryByText(/kunde inte uppdateras/)).toBeNull();
      expect(document.activeElement).toBe(retry);
    } finally {
      phase = "recovered";
      act(() => onlineManager.setOnline(true));
    }
    // Back online the refresh succeeds: no failure is left to report.
    await waitFor(() => expect(screen.queryByText("Det gick inte att läsa in fler.")).toBeNull());
    expect(screen.queryByText(/kunde inte uppdateras/)).toBeNull();
  });
});

describe("RefreshError", () => {
  function Filtered({
    filter,
    fetchNames
  }: {
    filter: string;
    fetchNames: (filter: string) => Promise<string[]>;
  }) {
    const list = useQuery({
      queryKey: ["filtered", filter],
      queryFn: () => fetchNames(filter),
      placeholderData: keepPreviousData
    });
    return (
      <QueryStateBoundary query={list}>
        {(items) => (
          <ul>
            {items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
      </QueryStateBoundary>
    );
  }

  it("drops a refresh failure when the filter changes to a query that has not failed", async () => {
    let failA = false;
    const fetchNames = vi.fn(async (filter: string) => {
      if (filter === "b") return new Promise<string[]>(() => {});
      if (failA) throw new Error("refresh failed");
      return ["Anna"];
    });
    const { queryClient, rerender } = renderInApp(<Filtered filter="a" fetchNames={fetchNames} />);
    await screen.findByText("Anna");

    failA = true;
    await queryClient.refetchQueries({ queryKey: ["filtered", "a"] });
    expect(await screen.findByText(/kunde inte uppdateras/)).toBeTruthy();

    rerender(<Filtered filter="b" fetchNames={fetchNames} />);
    await waitFor(() => expect(fetchNames).toHaveBeenLastCalledWith("b"));
    // B shows A's rows as a placeholder while it loads; A's failure is not B's.
    expect(screen.getByText("Anna")).toBeTruthy();
    expect(screen.queryByText(/kunde inte uppdateras/)).toBeNull();
  });
});
