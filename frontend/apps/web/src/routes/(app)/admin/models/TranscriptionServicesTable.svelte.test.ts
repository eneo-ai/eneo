import type { TranscriptionService, TranscriptionServiceCheck } from "@eneo/eneo-js";
import { EneoError } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, expect, it, vi } from "vitest";

const { update, check, invalidate } = vi.hoisted(() => ({
  update: vi.fn(),
  check: vi.fn(),
  invalidate: vi.fn()
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ transcriptionServices: { update, check } })
}));
vi.mock("$app/navigation", () => ({ invalidate }));

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
  space_count: 0,
  last_check: null,
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
  service_version: null,
  checked_at: new Date().toISOString()
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
  update.mockImplementation(async () => service());
  render(TranscriptionServicesTable, { services: [service()], classifications: [] });

  await actionsFor("Vemsa Sundsvall").click();
  await page.getByRole("menuitem", { name: m.speaker_service_test() }).click();
  await actionsFor("Vemsa Sundsvall").click();
  await page.getByRole("menuitem", { name: m.edit() }).click();
  // The dialog focuses its first field as it opens; type only after that.
  await expect.element(page.getByLabelText(m.name())).toHaveFocus();
  await page.getByLabelText(m.speaker_service_api_key()).fill("new-key");
  await page.getByRole("button", { name: m.save() }).click();

  // A new key starts a fresh check of what it saved.
  await expect.poll(() => check.mock.calls.length).toBe(2);
  const row = page.getByRole("row", { name: /Vemsa Sundsvall/ });
  after.resolve(result("ready"));
  await expect.element(row).toHaveTextContent(m.speaker_service_status_ready());
  before.resolve(result("unavailable"));
  await settle();
  await expect.element(row).not.toHaveTextContent(m.speaker_service_status_unavailable());
  await expect.element(row).toHaveTextContent(m.speaker_service_status_ready());
});

it("shows the stored check, when it ran and how many spaces use the service", async () => {
  render(TranscriptionServicesTable, {
    services: [service({ space_count: 2, last_check: result("ready") })],
    classifications: []
  });

  const row = page.getByRole("row", { name: /Vemsa Sundsvall/ });
  await expect.element(row).toHaveTextContent(m.speaker_service_used_in({ count: 2 }));
  await expect.element(row).toHaveTextContent(m.speaker_service_status_ready());
  await expect.element(row.getByRole("time")).toBeVisible();
});

it("does not test again after a change that keeps the address and key", async () => {
  update.mockImplementation(async () => service({ name: "Vemsa Nord" }));
  render(TranscriptionServicesTable, { services: [service()], classifications: [] });

  await actionsFor("Vemsa Sundsvall").click();
  await page.getByRole("menuitem", { name: m.edit() }).click();
  // The dialog focuses its first field as it opens; type only after that.
  await expect.element(page.getByLabelText(m.name())).toHaveFocus();
  await page.getByLabelText(m.name()).fill("Vemsa Nord");
  await page.getByRole("button", { name: m.save() }).click();

  await expect.element(page.getByRole("row", { name: /Vemsa Nord/ })).toBeVisible();
  expect(check).not.toHaveBeenCalled();
});

it("asks before switching off a service that spaces use, and keeps it on until confirmed", async () => {
  update.mockImplementation(async () => service({ space_count: 3, is_enabled: false }));
  render(TranscriptionServicesTable, {
    services: [service({ space_count: 3 })],
    classifications: []
  });

  const toggle = page.getByRole("switch", { name: "Vemsa Sundsvall" });
  await toggle.click();

  await expect
    .element(page.getByText(m.speaker_service_disable_description({ count: 3 })))
    .toBeVisible();
  await expect.element(toggle).toBeChecked();
  expect(update).not.toHaveBeenCalled();

  await page.getByRole("button", { name: m.speaker_service_disable_confirm() }).click();
  expect(update).toHaveBeenCalledWith({ id: "s1" }, { is_enabled: false });
  await expect.element(toggle).not.toBeChecked();
});

it("shows the check the server returns after a save, even one cleared by someone else", async () => {
  // Another administrator gave the service a new key meanwhile; the server
  // cleared its check, and a rename here must not bring the old one back.
  update.mockImplementation(async () => service({ name: "Vemsa Nord", last_check: null }));
  render(TranscriptionServicesTable, {
    services: [service({ last_check: result("ready") })],
    classifications: []
  });

  await actionsFor("Vemsa Sundsvall").click();
  await page.getByRole("menuitem", { name: m.edit() }).click();
  // The dialog focuses its first field as it opens; type only after that.
  await expect.element(page.getByLabelText(m.name())).toHaveFocus();
  await page.getByLabelText(m.name()).fill("Vemsa Nord");
  await page.getByRole("button", { name: m.save() }).click();

  const row = page.getByRole("row", { name: /Vemsa Nord/ });
  await expect.element(row).toHaveTextContent(m.speaker_service_not_tested());
  await expect.element(row).not.toHaveTextContent(m.speaker_service_status_ready());
});

it("reads a check timed a moment ahead of this clock as just now", async () => {
  const ahead = new Date(Date.now() + 5_000).toISOString();
  render(TranscriptionServicesTable, {
    services: [service({ last_check: { ...result("ready"), checked_at: ahead } })],
    classifications: []
  });

  const time = page.getByRole("row", { name: /Vemsa Sundsvall/ }).getByRole("time");
  await expect.element(time).toHaveTextContent(m.speaker_service_checked({ when: "nu" }));
});

it("drops a running check's answer once a save returns newer settings", async () => {
  // The check tested the old address; another administrator moved the service
  // meanwhile, and the rename here answered with the cleared check.
  const running = deferred<TranscriptionServiceCheck>();
  check.mockReturnValueOnce(running.promise);
  update.mockImplementation(async () =>
    service({ name: "Vemsa Nord", endpoint_url: "https://vemsa-nord.sundsvall.se" })
  );
  render(TranscriptionServicesTable, { services: [service()], classifications: [] });

  await actionsFor("Vemsa Sundsvall").click();
  await page.getByRole("menuitem", { name: m.speaker_service_test() }).click();
  await actionsFor("Vemsa Sundsvall").click();
  await page.getByRole("menuitem", { name: m.edit() }).click();
  await expect.element(page.getByLabelText(m.name())).toHaveFocus();
  await page.getByLabelText(m.name()).fill("Vemsa Nord");
  await page.getByRole("button", { name: m.save() }).click();
  const row = page.getByRole("row", { name: /Vemsa Nord/ });
  await expect.element(row).toHaveTextContent(m.speaker_service_not_tested());

  running.resolve(result("ready"));
  await settle();
  await expect.element(row).not.toHaveTextContent(m.speaker_service_status_ready());
  await expect.element(row).toHaveTextContent(m.speaker_service_not_tested());
});

it("keeps a failed list inside its section, with a way to try again", async () => {
  render(TranscriptionServicesTable, { services: null, classifications: [] });

  await expect.element(page.getByText(m.speaker_service_list_failed())).toBeVisible();
  await expect
    .element(page.getByRole("button", { name: m.speaker_service_connect() }))
    .not.toBeInTheDocument();
  await page.getByRole("button", { name: m.retry() }).click();
  expect(invalidate).toHaveBeenCalledWith("admin:models:load");
});
