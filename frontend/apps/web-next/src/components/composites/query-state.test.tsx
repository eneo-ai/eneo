// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ListError, QueryStateBoundary, type QueryLike } from "./query-state";

afterEach(cleanup);

function query<T>(overrides: Partial<QueryLike<T>>): QueryLike<T> {
  return {
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    isFetching: false,
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
