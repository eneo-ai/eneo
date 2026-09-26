// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
// The moves and the connection have their own tests.
vi.mock("./storage-content", () => ({ StorageContent: () => null }));
vi.mock("./storage-connection-section", () => ({ StorageConnectionSection: () => null }));

import { StorageAdminPage } from "./storage-admin-page";

afterEach(() => vi.clearAllMocks());

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

const problemsOf = (field: HTMLElement) =>
  (field.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent);

it("shows a limit out of range at its field on save, and keeps focus on a busy Save", async () => {
  api.GET.mockResolvedValue({ data: policy, response: new Response("{}") });
  api.PUT.mockReturnValue(new Promise(() => {}));
  const { container } = renderInApp(<StorageAdminPage />, {
    appContext: testAppContext({ permissions: ["storage"] })
  });
  const imageLimit = (await screen.findByLabelText("Gräns för sessionsbild")) as HTMLInputElement;

  fireEvent.change(imageLimit, { target: { value: "" } });
  // Nothing is flagged while typing.
  expect(imageLimit.getAttribute("aria-invalid")).toBeNull();
  const save = screen.getByRole("button", { name: "Spara inställningar" });
  expect(save.hasAttribute("disabled")).toBe(false);
  save.focus();
  fireEvent.click(save);

  expect(document.activeElement).toBe(imageLimit);
  expect(imageLimit.getAttribute("aria-invalid")).toBe("true");
  expect(problemsOf(imageLimit)).toEqual([
    "Ange ett positivt värde, till exempel 10 MB.",
    "Ange ett positivt värde och välj en enhet."
  ]);
  expect(api.PUT).not.toHaveBeenCalled();
  await expectNoAxeViolations(container);

  fireEvent.change(imageLimit, { target: { value: "2" } });
  expect(imageLimit.getAttribute("aria-invalid")).toBeNull();
  save.focus();
  fireEvent.click(save);
  const busy = await screen.findByRole("button", { name: "Sparar…" });
  expect(busy).toBe(save);
  expect(busy.getAttribute("aria-busy")).toBe("true");
  expect(document.activeElement).toBe(busy);
  fireEvent.click(busy);
  await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(1));
  expect(api.PUT.mock.calls[0]?.[1]).toMatchObject({
    body: { session_image_limit_bytes: 2048, expected_revision: 7 }
  });
});
