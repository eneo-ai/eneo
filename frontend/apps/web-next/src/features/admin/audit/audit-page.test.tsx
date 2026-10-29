// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { renderInApp } from "@/test/render";
import { replaceUrl } from "@/test/navigation";

const state = vi.hoisted(() => ({
  failLogs: false,
  requested: [] as string[],
  searches: [] as unknown[]
}));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string, options?: { params?: { query?: { search?: string } } }) => {
      state.requested.push(path);
      if (path === "/api/v1/audit/logs") {
        state.searches.push(options?.params?.query?.search);
        if (state.failLogs) {
          return Promise.reject(new EneoApiError("boom", { status: 500, code: 9024 }));
        }
        return Promise.resolve({
          data: {
            logs: [
              {
                id: "log-1",
                tenant_id: "tenant-1",
                actor_id: "5d0c7a2e-0000-4000-8000-000000000001",
                actor_type: "user",
                action: "user_created",
                entity_type: "user",
                entity_id: "5d0c7a2e-0000-4000-8000-000000000002",
                timestamp: "2026-09-25T08:30:00Z",
                description: "Användaren anna.lind@kommun.se skapades",
                metadata: {},
                outcome: "success",
                created_at: "2026-09-25T08:30:00Z",
                updated_at: "2026-09-25T08:30:00Z"
              }
            ],
            page: 1,
            page_size: 100,
            total_pages: 1,
            total_count: 1
          },
          response: new Response("{}")
        });
      }
      return Promise.resolve({ data: { actions: [] }, response: new Response("{}") });
    }
  }
}));

import { AuditPage } from "./audit-page";

beforeEach(() => {
  state.failLogs = false;
  state.requested = [];
  state.searches = [];
  window.history.replaceState(null, "", "/admin/audit");
});
afterEach(cleanup);

describe("AuditPage", () => {
  it("follows external filters and discards a pending search draft", async () => {
    renderInApp(<AuditPage />, { route: "/admin/audit" });
    await screen.findByRole("table", { name: "Granskningsloggar" });
    const search = screen.getByRole("textbox", { name: "Sök" });
    vi.useFakeTimers();
    try {
      fireEvent.change(search, { target: { value: "utkast" } });
      act(() => replaceUrl("/admin/audit?page=3&search=återställd&actions=user_created"));
      expect(search).toHaveProperty("value", "återställd");
      act(() => vi.advanceTimersByTime(300));
      expect(window.location.search).toBe(
        "?page=3&search=%C3%A5terst%C3%A4lld&actions=user_created"
      );
      expect(state.searches.at(-1)).toBe("återställd");
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows skeleton rows while the logs load, then the table, without the retention box", async () => {
    renderInApp(<AuditPage />, { route: "/admin/audit" });
    // Astryx controls carry their own (idle) live regions; the skeleton is the busy one.
    expect(
      screen.getAllByRole("status").some((region) => region.getAttribute("aria-busy") === "true")
    ).toBe(true);

    expect(await screen.findByRole("table", { name: "Granskningsloggar" })).toBeTruthy();
    expect(screen.queryByText("Gallringspolicy")).toBeNull();
    expect(state.requested).not.toContain("/api/v1/audit/retention-policy");
  });

  it("shows the shared error state and loads the logs again on retry", async () => {
    state.failLogs = true;
    renderInApp(<AuditPage />, { route: "/admin/audit" });

    expect(await screen.findByText("Innehållet kunde inte hämtas")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();

    state.failLogs = false;
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    await waitFor(() =>
      expect(screen.getByRole("table", { name: "Granskningsloggar" })).toBeTruthy()
    );
  });

  it("searches again for a search restored right after clearing it", async () => {
    renderInApp(<AuditPage />, { route: "/admin/audit" });
    await screen.findByRole("table", { name: "Granskningsloggar" });
    const search = screen.getByRole("textbox", { name: "Sök" });

    vi.useFakeTimers();
    try {
      fireEvent.change(search, { target: { value: "abc" } });
      act(() => vi.advanceTimersByTime(300));
      expect(window.location.search).toBe("?search=abc");

      // Clearing applies at once; typing the same search back applies again.
      fireEvent.change(search, { target: { value: "" } });
      expect(window.location.search).toBe("");
      fireEvent.change(search, { target: { value: "abc" } });
      act(() => vi.advanceTimersByTime(300));
      expect(window.location.search).toBe("?search=abc");
      expect(state.searches.at(-1)).toBe("abc");
    } finally {
      vi.useRealTimers();
    }
  });
});
