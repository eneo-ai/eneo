// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const put = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, POST: post, PUT: put } }));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => "en"
}));

import { StorageContent } from "./storage-content";

const policy: Schema<"DeploymentPolicyPublic"> = {
  policy: {
    revision: 7,
    new_write_storage_target: "postgres_inline",
    session_file_limit_bytes: 1024,
    session_image_limit_bytes: 1024,
    knowledge_file_limit_bytes: 1024,
    transcription_audio_limit_bytes: 1024,
    moves_paused: false,
    updated_by_actor: "storage_admin",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z"
  },
  limits: [],
  capabilities: [
    { target: "object_store", configured: true, selectable: true, readiness_code: "ready" }
  ]
};
const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });

beforeEach(() => {
  get.mockImplementation((path: string) =>
    path.endsWith("inventory")
      ? ok({ inventory: [], postgresql_allocation: null })
      : ok({ policy_revision: 7, paused: false, moves: [] })
  );
  post.mockImplementation(() => ok({ queued_count: 2, target_too_large_count: 0 }));
  put.mockImplementation(() => ok({ policy_revision: 8, paused: true }));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderContent() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onPolicyPaused = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <StorageContent
        policy={policy}
        dirtyPolicyDraft={false}
        policyBusy={false}
        onAuthorityRevoked={vi.fn()}
        onPolicyPaused={onPolicyPaused}
        onRefreshPolicy={vi.fn().mockResolvedValue(undefined)}
      />
    </QueryClientProvider>
  );
  return { onPolicyPaused };
}

describe("storage move commands", () => {
  it("queues only after confirmation and uses the selected target and bounded batch", async () => {
    renderContent();
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByLabelText("storage_moves_target"), {
      target: { value: "object_store" }
    });
    fireEvent.change(screen.getByLabelText("storage_moves_limit"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "storage_moves_queue" }));
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "storage_moves_confirm_action" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/admin/object-content-moves", {
        body: { target: "object_store", limit: 12 }
      })
    );
  });

  it("pauses against the status revision and reports the new revision", async () => {
    const { onPolicyPaused } = renderContent();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "storage_moves_pause" })).toBeTruthy()
    );
    fireEvent.click(screen.getByRole("button", { name: "storage_moves_pause" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/v1/admin/object-content-moves/pause", {
        body: { expected_revision: 7, moves_paused: true }
      })
    );
    expect(onPolicyPaused).toHaveBeenCalledWith(7, 8, true);
  });

  it("blocks new commands while move status is unavailable", async () => {
    get.mockImplementation((path: string) =>
      path.endsWith("inventory")
        ? ok({ inventory: [], postgresql_allocation: null })
        : Promise.resolve({
            error: { message: "Unavailable" },
            response: new Response("{}", { status: 503 })
          })
    );
    renderContent();
    await waitFor(() =>
      expect(screen.getAllByText("storage_moves_load_error_title").length).toBeGreaterThan(0)
    );
    expect(
      screen.getByRole("button", { name: "storage_moves_queue" }).hasAttribute("disabled")
    ).toBe(true);
    expect(put).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
});
