// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
// The moves and the connection have their own tests.
vi.mock("./storage-content", () => ({ StorageContent: () => null }));
vi.mock("./storage-connection-section", () => ({
  StorageConnectionSection: ({
    onConnectionChanged,
    capability
  }: {
    onConnectionChanged: () => Promise<void>;
    capability?: Schema<"DeploymentPolicyPublic">["capabilities"][number];
  }) => (
    <button onClick={() => void onConnectionChanged()}>
      {capability?.readiness_code ?? "missing"}
    </button>
  )
}));

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

it("refreshes storage capabilities and dependent data after a connection change while keeping an unsaved policy", async () => {
  api.GET.mockResolvedValueOnce({ data: policy, response: new Response("{}") });
  api.GET.mockResolvedValueOnce({
    data: {
      ...policy,
      capabilities: [
        { ...policy.capabilities[0], selectable: false, readiness_code: "unavailable" }
      ]
    },
    response: new Response("{}")
  });
  const { queryClient } = renderInApp(<StorageAdminPage />, {
    appContext: testAppContext({ permissions: ["storage"] })
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const imageLimit = (await screen.findByLabelText("Gräns för sessionsbild")) as HTMLInputElement;
  fireEvent.change(imageLimit, { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "ready" }));
  await screen.findByRole("button", { name: "unavailable" });
  expect(imageLimit.value).toBe("2");
  expect(api.GET).toHaveBeenCalledTimes(2);
  expect(invalidate.mock.calls).toEqual([
    [{ queryKey: ["storage-inventory"] }],
    [{ queryKey: ["storage-moves"] }]
  ]);
  expect(api.PUT).not.toHaveBeenCalled();
});

const MIB = 1024 * 1024;
const limitsWith = (
  target: "postgres_inline" | "object_store",
  ceiling: number,
  configured: number
): Schema<"DeploymentPolicyPublic">["limits"] =>
  (
    ["session_file", "session_image", "session_audio", "knowledge_file", "knowledge_audio"] as const
  ).map((use_case) => ({
    use_case,
    configured_bytes: configured,
    effective_bytes: Math.min(configured, ceiling),
    storage_target: target,
    operator_ceiling_bytes: ceiling,
    constraining_source: ceiling < configured ? "operator_ceiling" : "admin_policy"
  }));

const databaseCeiling =
  "Filer som lagras i databasen har också en lagringsgräns: det mesta PostgreSQL rymmer per fil, eller mindre om den föråldrade miljövariabeln OBJECT_CONTENT_INLINE_MAXIMUM_BYTES fortfarande är satt. Driften tar bort variabeln så att gränserna ovan gäller.";
const databaseCost =
  "Varje uppladdning läses in helt i minnet, och varje fil hamnar i databasens säkerhetskopia.";

it("says the deprecated variable can hold the database storage limit below the policy", async () => {
  // A set OBJECT_CONTENT_INLINE_MAXIMUM_BYTES of 10 MiB under a 300 MiB policy.
  api.GET.mockResolvedValue({
    data: { ...policy, limits: limitsWith("postgres_inline", 10 * MIB, 300 * MIB) },
    response: new Response("{}")
  });
  renderInApp(<StorageAdminPage />, { appContext: testAppContext({ permissions: ["storage"] }) });

  expect(await screen.findByText(databaseCeiling)).toBeTruthy();
  expect(
    screen.getByText(
      "Lagringsgränsen är 10 MB, lägre än några av gränserna ovan, så de uppladdningarna stoppas där."
    )
  ).toBeTruthy();
  expect(screen.getByText(databaseCost)).toBeTruthy();
});

it("explains the database storage limit without a lower limit once the variable is gone", async () => {
  api.GET.mockResolvedValue({
    data: { ...policy, limits: limitsWith("postgres_inline", 536_870_399, 300 * MIB) },
    response: new Response("{}")
  });
  renderInApp(<StorageAdminPage />, { appContext: testAppContext({ permissions: ["storage"] }) });

  expect(await screen.findByText(databaseCeiling)).toBeTruthy();
  expect(screen.getByText(databaseCost)).toBeTruthy();
  expect(screen.queryByText(/^Lagringsgränsen är/)).toBeNull();
});

it("keeps the database storage notes away from object storage", async () => {
  api.GET.mockResolvedValue({
    data: {
      ...policy,
      policy: { ...policy.policy, new_write_storage_target: "object_store" },
      limits: limitsWith("object_store", 83_886_080_000, 300 * MIB)
    },
    response: new Response("{}")
  });
  renderInApp(<StorageAdminPage />, { appContext: testAppContext({ permissions: ["storage"] }) });

  await screen.findByLabelText("Gräns för sessionsbild");
  expect(screen.queryByText(databaseCeiling)).toBeNull();
  expect(screen.queryByText(databaseCost)).toBeNull();
});
