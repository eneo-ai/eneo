// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { renderInApp } from "@/test/render";

const state = vi.hoisted(() => ({ failLogs: false, requested: [] as string[] }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      state.requested.push(path);
      if (path === "/api/v1/audit/logs") {
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
});
afterEach(cleanup);

describe("AuditPage", () => {
  it("shows skeleton rows while the logs load, then the table, without the retention box", async () => {
    renderInApp(<AuditPage />);
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
    renderInApp(<AuditPage />);

    expect(await screen.findByText("Innehållet kunde inte hämtas")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();

    state.failLogs = false;
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    await waitFor(() =>
      expect(screen.getByRole("table", { name: "Granskningsloggar" })).toBeTruthy()
    );
  });
});
