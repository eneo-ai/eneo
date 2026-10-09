import type { TranscriptionService, TranscriptionServiceCheck } from "@eneo/eneo-js";
import { EneoError } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, expect, it, vi } from "vitest";

const { update, check } = vi.hoisted(() => ({ update: vi.fn(), check: vi.fn() }));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ transcriptionServices: { update, check } })
}));

import TranscriptionServicesTable from "./TranscriptionServicesTable.svelte";
import { m } from "$lib/paraglide/messages";

const classification = {
  id: "c1",
  name: "Intern",
  description: null,
  security_level: 2
};

const service = (overrides: Partial<TranscriptionService> = {}): TranscriptionService => ({
  id: "s1",
  name: "Vemsa Sundsvall",
  endpoint_url: "https://vemsa.sundsvall.se",
  is_enabled: true,
  security_classification: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  ...overrides
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolver) => (resolve = resolver));
  return { promise, resolve };
}

// Lets every settled request reach the page before a "still not shown" check.
const settle = () => new Promise((resolve) => setTimeout(resolve, 50));

const result = (outcome: TranscriptionServiceCheck["outcome"]): TranscriptionServiceCheck => ({
  outcome,
  detail: "",
  identifies_speakers: true,
  service_version: null
});

const actionsFor = (name: string) =>
  page.getByRole("button", { name: m.speaker_service_actions({ name }) });

beforeEach(() => {
  update.mockReset();
  check.mockReset();
});

it("invites a first connection when the organisation has none", async () => {
  render(TranscriptionServicesTable, { services: [], classifications: [classification] });

  await expect.element(page.getByText(m.speaker_service_empty_title())).toBeVisible();
  await expect
    .element(page.getByRole("button", { name: m.speaker_service_connect() }))
    .toBeVisible();
  await expect.element(page.getByRole("table")).not.toBeInTheDocument();
});

it("shows the host, the classification and that the connection is untested", async () => {
  render(TranscriptionServicesTable, {
    services: [service({ security_classification: classification })],
    classifications: [classification]
  });

  const row = page.getByRole("row", { name: /Vemsa Sundsvall/ });
  await expect.element(row).toHaveTextContent("vemsa.sundsvall.se");
  await expect.element(row).toHaveTextContent("Intern");
  await expect.element(row).toHaveTextContent(m.speaker_service_not_tested());
});

it("turns a service off at once and turns it back on when the save fails", async () => {
  let fail = (_error: unknown) => {};
  update.mockReturnValueOnce(new Promise((_resolve, reject) => (fail = reject)));
  render(TranscriptionServicesTable, { services: [service()], classifications: [] });

  const toggle = page.getByRole("switch", { name: "Vemsa Sundsvall" });
  await toggle.click();
  expect(update).toHaveBeenCalledWith({ id: "s1" }, { is_enabled: false });
  await expect.element(toggle).not.toBeChecked();

  fail(new EneoError("Service unavailable", "SERVER", 503, 0));
  await expect.element(toggle).toBeChecked();
});

it("holds a service's switch and changes while one is saving, but not its test", async () => {
  update.mockReturnValueOnce(new Promise(() => {}));
  render(TranscriptionServicesTable, { services: [service()], classifications: [] });

  const toggle = page.getByRole("switch", { name: "Vemsa Sundsvall" });
  await toggle.click();
  await expect.element(toggle).toBeDisabled();

  await actionsFor("Vemsa Sundsvall").click();
  await expect
    .element(page.getByRole("menuitem", { name: m.edit() }))
    .toHaveAttribute("aria-disabled", "true");
  await expect
    .element(page.getByRole("menuitem", { name: m.remove() }))
    .toHaveAttribute("aria-disabled", "true");
  await expect
    .element(page.getByRole("menuitem", { name: m.speaker_service_test() }))
    .toHaveAttribute("aria-disabled", "false");
});

it("never brings back a service that left the list while its change was saving", async () => {
  const saving = deferred<TranscriptionService>();
  update.mockReturnValueOnce(saving.promise);
  const { rerender } = render(TranscriptionServicesTable, {
    services: [service()],
    classifications: []
  });

  await page.getByRole("switch", { name: "Vemsa Sundsvall" }).click();
  // The page reloaded without it, for instance after another administrator removed it.
  await rerender({ services: [] });
  saving.resolve(service({ is_enabled: false }));
  await settle();

  await expect.element(page.getByText(m.speaker_service_empty_title())).toBeVisible();
  await expect.element(page.getByRole("table")).not.toBeInTheDocument();
});

it("shows only the check of the saved settings when one was running before the save", async () => {
  const before = deferred<TranscriptionServiceCheck>();
  const after = deferred<TranscriptionServiceCheck>();
  check.mockReturnValueOnce(before.promise).mockReturnValueOnce(after.promise);
  update.mockImplementation(async (_id: unknown, body: Partial<TranscriptionService>) =>
    service(body)
  );
  render(TranscriptionServicesTable, { services: [service()], classifications: [] });

  await actionsFor("Vemsa Sundsvall").click();
  await page.getByRole("menuitem", { name: m.speaker_service_test() }).click();
  await actionsFor("Vemsa Sundsvall").click();
  await page.getByRole("menuitem", { name: m.edit() }).click();
  await page.getByLabelText(m.name()).fill("Vemsa Sundsvall Nord");
  await page.getByRole("button", { name: m.save() }).click();

  // The save starts a fresh check of what it saved.
  await expect.poll(() => check.mock.calls.length).toBe(2);
  const row = page.getByRole("row", { name: /Vemsa Sundsvall Nord/ });
  after.resolve(result("ready"));
  await expect.element(row).toHaveTextContent(m.speaker_service_status_ready());
  before.resolve(result("unavailable"));
  await settle();
  await expect.element(row).not.toHaveTextContent(m.speaker_service_status_unavailable());
  await expect.element(row).toHaveTextContent(m.speaker_service_status_ready());
});
