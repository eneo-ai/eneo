import type { TranscriptionService, TranscriptionServiceCheck } from "@eneo/eneo-js";
import { EneoError } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, expect, it, vi } from "vitest";

const { create, update, check, invalidate } = vi.hoisted(() => ({
  create: vi.fn(),
  update: vi.fn(),
  check: vi.fn(),
  invalidate: vi.fn()
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ transcriptionServices: { create, update, check } })
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
  is_default: false,
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
  times_words: true,
  reason: null,
  status_code: null,
  service_version: null,
  checked_at: new Date().toISOString()
});

const actionsFor = (name: string) =>
  page.getByRole("button", { name: m.speaker_service_actions({ name }) });

beforeEach(() => {
  create.mockReset();
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

it("shows the default and moves the mark when another service is made the default", async () => {
  const timra = service({ id: "s2", name: "Vemsa Timrå", endpoint_url: "https://vemsa.timra.se" });
  update.mockImplementation(async () => ({ ...timra, is_default: true }));
  render(TranscriptionServicesTable, {
    services: [service({ is_default: true }), timra],
    classifications: []
  });
  const sundsvall = page.getByRole("row", { name: /Vemsa Sundsvall/ });
  const other = page.getByRole("row", { name: /Vemsa Timrå/ });
  await expect.element(sundsvall).toHaveTextContent(m.speaker_service_default_badge());
  await expect.element(other).not.toHaveTextContent(m.speaker_service_default_badge());

  await makeDefault("Vemsa Timrå");

  // Only the change is sent, and only one service is the default afterwards.
  expect(update).toHaveBeenCalledWith({ id: "s2" }, { is_default: true });
  await expect.element(other).toHaveTextContent(m.speaker_service_default_badge());
  await expect.element(sundsvall).not.toHaveTextContent(m.speaker_service_default_badge());
  expect(check).not.toHaveBeenCalled();
});

async function makeDefault(name: string) {
  await actionsFor(name).click();
  await page.getByRole("menuitem", { name: m.edit() }).click();
  await expect.element(page.getByLabelText(m.name())).toHaveFocus();
  await page.getByLabelText(m.speaker_service_default_label()).click();
  await page.getByRole("button", { name: m.save() }).click();
}

it("connects a service as the default when the box is ticked, taking the mark from the other", async () => {
  const timra = service({ id: "s2", name: "Vemsa Timrå", endpoint_url: "https://vemsa.timra.se" });
  create.mockImplementation(async () => timra);
  update.mockImplementation(async () => ({ ...timra, is_default: true }));
  check.mockImplementation(async () => result("ready"));
  render(TranscriptionServicesTable, {
    services: [service({ is_default: true })],
    classifications: []
  });

  await page.getByRole("button", { name: m.speaker_service_connect() }).click();
  await page.getByLabelText(m.name()).fill(timra.name);
  await page.getByLabelText(m.speaker_service_address()).fill(timra.endpoint_url);
  await page.getByLabelText(m.speaker_service_api_key()).fill("key");
  await page.getByLabelText(m.speaker_service_default_label()).click();
  await page.getByRole("button", { name: m.speaker_service_connect_submit(), exact: true }).click();

  // Connected first, then marked through the path that moves the mark.
  await vi.waitFor(() => expect(update).toHaveBeenCalledWith({ id: "s2" }, { is_default: true }));
  expect(create.mock.calls[0][0]).not.toHaveProperty("is_default");
  await expect
    .element(page.getByRole("row", { name: /Vemsa Timrå/ }))
    .toHaveTextContent(m.speaker_service_default_badge());
  await expect
    .element(page.getByRole("row", { name: /Vemsa Sundsvall/ }))
    .not.toHaveTextContent(m.speaker_service_default_badge());
});

it("shows the test of a service connected as the default, though the mark is saved while it runs", async () => {
  const timra = service({ id: "s2", name: "Vemsa Timrå", endpoint_url: "https://vemsa.timra.se" });
  const running = deferred<TranscriptionServiceCheck>();
  create.mockImplementation(async () => timra);
  update.mockImplementation(async () => ({ ...timra, is_default: true }));
  check.mockReturnValueOnce(running.promise).mockImplementation(async () => result("ready"));
  render(TranscriptionServicesTable, { services: [], classifications: [] });

  await page.getByRole("button", { name: m.speaker_service_connect() }).click();
  await page.getByLabelText(m.name()).fill(timra.name);
  await page.getByLabelText(m.speaker_service_address()).fill(timra.endpoint_url);
  await page.getByLabelText(m.speaker_service_api_key()).fill("key");
  await page.getByLabelText(m.speaker_service_default_label()).click();
  await page.getByRole("button", { name: m.speaker_service_connect_submit(), exact: true }).click();
  await vi.waitFor(() => expect(update).toHaveBeenCalledWith({ id: "s2" }, { is_default: true }));

  // Saving the mark interrupted the test; it runs again and its answer is shown.
  running.resolve({ ...result("unavailable"), reason: "timeout" });
  await expect
    .element(page.getByRole("dialog").getByText(m.speaker_service_check_words_and_speakers()))
    .toBeVisible();
});

it("keeps one default when a slower answer to another edit arrives after the mark moved", async () => {
  const timra = service({ id: "s2", name: "Vemsa Timrå", endpoint_url: "https://vemsa.timra.se" });
  const switchingOff = deferred<TranscriptionService>();
  update
    .mockReturnValueOnce(switchingOff.promise)
    .mockImplementationOnce(async () => ({ ...timra, is_default: true }));
  render(TranscriptionServicesTable, {
    services: [service({ is_default: true }), timra],
    classifications: []
  });
  const sundsvall = page.getByRole("row", { name: /Vemsa Sundsvall/ });
  const other = page.getByRole("row", { name: /Vemsa Timrå/ });

  // Switching the default off is sent while it still carries the mark.
  await page.getByRole("switch", { name: "Vemsa Sundsvall" }).click();
  await makeDefault("Vemsa Timrå");
  await expect.element(other).toHaveTextContent(m.speaker_service_default_badge());
  switchingOff.resolve(service({ is_enabled: false, is_default: true }));
  await settle();

  await expect.element(other).toHaveTextContent(m.speaker_service_default_badge());
  await expect.element(sundsvall).not.toHaveTextContent(m.speaker_service_default_badge());
  await expect.element(page.getByRole("switch", { name: "Vemsa Sundsvall" })).not.toBeChecked();
});

it("leaves the default alone when the service being marked has left the list", async () => {
  const timra = service({ id: "s2", name: "Vemsa Timrå", endpoint_url: "https://vemsa.timra.se" });
  const marking = deferred<TranscriptionService>();
  update.mockReturnValueOnce(marking.promise);
  const { rerender } = render(TranscriptionServicesTable, {
    services: [service(), timra],
    classifications: []
  });

  await makeDefault("Vemsa Timrå");
  // The page reloaded: another administrator removed that service and marked this one.
  await rerender({ services: [service({ is_default: true })] });
  marking.resolve({ ...timra, is_default: true });
  await settle();

  await expect
    .element(page.getByRole("row", { name: /Vemsa Sundsvall/ }))
    .toHaveTextContent(m.speaker_service_default_badge());
  await expect.element(page.getByRole("row", { name: /Vemsa Timrå/ })).not.toBeInTheDocument();
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

it("drops a running check's answer once a save returns newer settings, and checks again", async () => {
  // The check tested the old address; another administrator moved the service
  // meanwhile, and the rename here answered with the cleared check.
  const running = deferred<TranscriptionServiceCheck>();
  const again = deferred<TranscriptionServiceCheck>();
  check.mockReturnValueOnce(running.promise).mockReturnValueOnce(again.promise);
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
  await expect.element(row).toHaveTextContent(m.speaker_service_testing());

  running.resolve(result("ready"));
  await settle();
  await expect.element(row).not.toHaveTextContent(m.speaker_service_status_ready());
  // The check it interrupted runs again, against the settings saved now.
  expect(check).toHaveBeenCalledTimes(2);
  again.resolve({ ...result("unavailable"), reason: "unreachable" });
  await expect.element(row).toHaveTextContent(m.speaker_service_status_unavailable());
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
