// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import type { Schema } from "@/lib/api/models";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

import { TranscriptionServicesSection } from "./transcription-services-section";
import { TRANSCRIPTION_SERVICES_KEY, type TranscriptionService } from "./transcription-services";

type Check = Schema<"TranscriptionServiceCheckPublic">;

const classification = { id: "c1", name: "Intern", description: null, security_level: 2 };

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
const timra = () =>
  service({ id: "s2", name: "Vemsa Timrå", endpoint_url: "https://vemsa.timra.se" });

const result = (outcome: Check["outcome"]): Check => ({
  outcome,
  detail: "",
  identifies_speakers: true,
  times_words: true,
  reason: null,
  status_code: null,
  service_version: null,
  checked_at: new Date().toISOString()
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((success, failure) => {
    resolve = success;
    reject = failure;
  });
  return { promise, resolve, reject };
}

// The service's answers; each test sets what they return.
const create = vi.fn<(body: unknown) => Promise<TranscriptionService>>();
const update = vi.fn<(id: string, body: unknown) => Promise<TranscriptionService>>();
const check = vi.fn<(id: string) => Promise<Check>>();
const remove = vi.fn<(id: string) => Promise<void>>();

/** openapi-fetch's result for an answer, or a 503 for a failure. */
const answer = (data: Promise<unknown>) =>
  data.then(
    (value) => ({ data: value, response: new Response("{}") }),
    () => ({
      error: { message: "Service unavailable" },
      response: new Response("{}", { status: 503 })
    })
  );

type Init = { params?: { path?: { connection_id?: string } }; body?: unknown };
const idOf = (init: Init) => init.params?.path?.connection_id ?? "";

let list: TranscriptionService[] | null = [];

beforeEach(() => {
  create.mockReset();
  update.mockReset();
  check.mockReset();
  remove.mockReset().mockResolvedValue(undefined);
  api.GET.mockImplementation(() =>
    list === null
      ? answer(Promise.reject(new Error("down")))
      : answer(Promise.resolve({ items: list, has_more: false }))
  );
  api.POST.mockImplementation((path: string, init: Init) =>
    answer(path.endsWith("/check/") ? check(idOf(init)) : create(init.body))
  );
  api.PATCH.mockImplementation((_path: string, init: Init) =>
    answer(update(idOf(init), init.body))
  );
  api.DELETE.mockImplementation((_path: string, init: Init) => answer(remove(idOf(init))));
});

afterEach(() => {
  cleanup();
  document.querySelectorAll("[data-astryx-live-region]").forEach((region) => region.remove());
  vi.clearAllMocks();
});

function renderSection(services: TranscriptionService[] | null) {
  list = services;
  const queryClient = testQueryClient();
  if (services) queryClient.setQueryData(TRANSCRIPTION_SERVICES_KEY, services);
  renderInApp(<TranscriptionServicesSection classifications={[classification]} />, {
    queryClient
  });
  return {
    queryClient,
    // The list as read again: another administrator changed it meanwhile.
    reload: (next: TranscriptionService[]) =>
      act(() => queryClient.setQueryData(TRANSCRIPTION_SERVICES_KEY, next))
  };
}

const row = (name: RegExp) => screen.getByRole("row", { name });
const toggle = (name: string) => screen.getByRole("switch", { name }) as HTMLInputElement;

/** Opens a service's menu from the keyboard; returns the menu. */
function openMenu(name: string) {
  const trigger = screen.getByRole("button", { name: `Åtgärder för ${name}` });
  trigger.focus();
  // jsdom does not turn Enter into a click; Astryx opens menus on the key.
  fireEvent.keyDown(trigger, { key: "Enter" });
  return document.getElementById(trigger.getAttribute("aria-controls")!)!;
}

function choose(name: string, item: string) {
  fireEvent.click(within(openMenu(name)).getByRole("menuitem", { name: item }));
}

const type = (label: RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

async function editAndSave(name: string, change: () => void) {
  choose(name, "Redigera");
  await screen.findByRole("dialog");
  change();
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
}

const makeDefault = (name: string) =>
  editAndSave(name, () => fireEvent.click(screen.getByLabelText(/^Standard för nya flöden/)));

// Lets every settled request reach the page before a "still not shown" check.
const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 20)));

it("invites a first connection when the organisation has none", async () => {
  renderSection([]);

  expect(screen.getByText("Ingen tjänst för ordtider och talare ansluten")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Anslut tjänst" })).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  await act(async () => {
    await expectNoAxeViolations(document.body);
  });
});

it("shows the host, the classification and that the connection is untested", async () => {
  renderSection([service({ security_classification: classification })]);

  const vemsa = row(/Vemsa Sundsvall/);
  expect(vemsa.textContent).toContain("vemsa.sundsvall.se");
  expect(vemsa.textContent).toContain("Intern");
  expect(vemsa.textContent).toContain("Inte testad");
  const table = screen.getByRole("table", { name: "Ordtider och talaridentifiering" });
  // An iPad held upright leaves it 682 px beside the icon rail: it fits whole.
  expect(Number.parseFloat(table.style.minWidth)).toBeLessThanOrEqual(682);
  await act(async () => {
    await expectNoAxeViolations(document.body);
  });
});

it("turns a service off at once and turns it back on when the save fails", async () => {
  const saving = deferred<TranscriptionService>();
  update.mockReturnValueOnce(saving.promise);
  renderSection([service()]);

  fireEvent.click(toggle("Vemsa Sundsvall"));
  expect(update).toHaveBeenCalledWith("s1", { is_enabled: false });
  await waitFor(() => expect(toggle("Vemsa Sundsvall").checked).toBe(false));

  await act(async () => saving.reject(new Error("offline")));
  await waitFor(() => expect(toggle("Vemsa Sundsvall").checked).toBe(true));
  expect(toast.error).toHaveBeenCalled();
});

it("holds a service's switch and changes while one is saving, but not its test", async () => {
  update.mockReturnValueOnce(new Promise(() => {}));
  renderSection([service()]);

  fireEvent.click(toggle("Vemsa Sundsvall"));
  // Kept enabled, so it keeps the focus it was just given, but busy: a press
  // meanwhile sends nothing.
  await waitFor(() => expect(toggle("Vemsa Sundsvall").getAttribute("aria-busy")).toBe("true"));
  expect(toggle("Vemsa Sundsvall").getAttribute("aria-disabled")).toBeNull();
  fireEvent.click(toggle("Vemsa Sundsvall"));
  expect(update).toHaveBeenCalledOnce();

  const menu = openMenu("Vemsa Sundsvall");
  expect(
    within(menu).getByRole("menuitem", { name: "Redigera" }).getAttribute("aria-disabled")
  ).toBe("true");
  expect(
    within(menu).getByRole("menuitem", { name: "Ta bort" }).getAttribute("aria-disabled")
  ).toBe("true");
  expect(
    within(menu).getByRole("menuitem", { name: "Testa anslutningen" }).getAttribute("aria-disabled")
  ).not.toBe("true");
});

it("never brings back a service that left the list while its change was saving", async () => {
  const saving = deferred<TranscriptionService>();
  update.mockReturnValueOnce(saving.promise);
  const { reload } = renderSection([service()]);

  fireEvent.click(toggle("Vemsa Sundsvall"));
  // The list was read again without it, after another administrator removed it.
  reload([]);
  await act(async () => saving.resolve(service({ is_enabled: false })));
  await settle();

  expect(screen.getByText("Ingen tjänst för ordtider och talare ansluten")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
});

it("shows only the check of the saved settings when one was running before the save", async () => {
  const before = deferred<Check>();
  const after = deferred<Check>();
  check.mockReturnValueOnce(before.promise).mockReturnValueOnce(after.promise);
  update.mockImplementation(async () => service());
  renderSection([service()]);

  choose("Vemsa Sundsvall", "Testa anslutningen");
  await editAndSave("Vemsa Sundsvall", () => type(/^API-nyckel/, "new-key"));

  // A new key starts a fresh check of what it saved.
  await waitFor(() => expect(check).toHaveBeenCalledTimes(2));
  await act(async () => after.resolve(result("ready")));
  await waitFor(() => expect(row(/Vemsa Sundsvall/).textContent).toContain("Tar emot jobb"));
  await act(async () => before.resolve(result("unavailable")));
  await settle();
  expect(row(/Vemsa Sundsvall/).textContent).not.toContain("Inte tillgänglig");
  expect(row(/Vemsa Sundsvall/).textContent).toContain("Tar emot jobb");
});

it("shows the stored check, when it ran and how many spaces use the service", () => {
  renderSection([service({ space_count: 2, last_check: result("ready") })]);

  const vemsa = row(/Vemsa Sundsvall/);
  expect(vemsa.textContent).toContain("Används i 2 ytor");
  expect(vemsa.textContent).toContain("Tar emot jobb");
  expect(vemsa.textContent).toContain("Ordtider och talare");
  expect(
    within(vemsa)
      .getByText(/Testad/)
      .querySelector("time")
  ).toBeTruthy();
});

it("reads a check timed a moment ahead of this clock as just now", () => {
  const ahead = new Date(Date.now() + 5_000).toISOString();
  renderSection([service({ last_check: { ...result("ready"), checked_at: ahead } })]);

  expect(within(row(/Vemsa Sundsvall/)).getByText(/Testad/).textContent).toContain("Testad nu");
});

it("does not test again after a change that keeps the address and key", async () => {
  update.mockImplementation(async () => service({ name: "Vemsa Nord" }));
  renderSection([service()]);

  await editAndSave("Vemsa Sundsvall", () => type(/^Namn/, "Vemsa Nord"));

  expect(await screen.findByRole("row", { name: /Vemsa Nord/ })).toBeTruthy();
  expect(check).not.toHaveBeenCalled();
});

it("shows the default and moves the mark when another service is made the default", async () => {
  update.mockImplementation(async () => ({ ...timra(), is_default: true }));
  renderSection([service({ is_default: true }), timra()]);
  expect(row(/Vemsa Sundsvall/).textContent).toContain("Standard");
  expect(row(/Vemsa Timrå/).textContent).not.toContain("Standard");

  await makeDefault("Vemsa Timrå");

  // Only the change is sent, and only one service is the default afterwards.
  await waitFor(() => expect(update).toHaveBeenCalledWith("s2", { is_default: true }));
  await waitFor(() => expect(row(/Vemsa Timrå/).textContent).toContain("Standard"));
  expect(row(/Vemsa Sundsvall/).textContent).not.toContain("Standard");
  expect(check).not.toHaveBeenCalled();
});

async function connect(name: string, address: string, asDefault: boolean) {
  fireEvent.click(screen.getByRole("button", { name: "Anslut tjänst" }));
  await screen.findByRole("dialog");
  type(/^Namn/, name);
  type(/^Adress/, address);
  type(/^API-nyckel/, "key");
  if (asDefault) fireEvent.click(screen.getByLabelText(/^Standard för nya flöden/));
  fireEvent.click(screen.getByRole("button", { name: "Anslut" }));
}

it("connects a service as the default when the box is ticked, taking the mark from the other", async () => {
  create.mockImplementation(async () => timra());
  update.mockImplementation(async () => ({ ...timra(), is_default: true }));
  check.mockImplementation(async () => result("ready"));
  renderSection([service({ is_default: true })]);

  await connect("Vemsa Timrå", "https://vemsa.timra.se", true);

  // Connected first, then marked through the path that moves the mark.
  await waitFor(() => expect(update).toHaveBeenCalledWith("s2", { is_default: true }));
  expect(create.mock.calls[0]![0]).not.toHaveProperty("is_default");
  await waitFor(() => expect(row(/Vemsa Timrå/).textContent).toContain("Standard"));
  expect(row(/Vemsa Sundsvall/).textContent).not.toContain("Standard");
});

it("shows the test of a service connected as the default, though the mark is saved while it runs", async () => {
  const running = deferred<Check>();
  create.mockImplementation(async () => timra());
  update.mockImplementation(async () => ({ ...timra(), is_default: true }));
  check.mockReturnValueOnce(running.promise).mockImplementation(async () => result("ready"));
  renderSection([]);

  await connect("Vemsa Timrå", "https://vemsa.timra.se", true);
  await waitFor(() => expect(update).toHaveBeenCalledWith("s2", { is_default: true }));

  // Saving the mark interrupted the test; it runs again and its answer is shown.
  await act(async () => running.resolve({ ...result("unavailable"), reason: "timeout" }));
  expect(
    await within(screen.getByRole("dialog")).findByText(
      "Tjänsten ger ordtider och kan identifiera talare."
    )
  ).toBeTruthy();
  // The answer is announced, without moving focus.
  await waitFor(() =>
    expect(document.querySelector("[data-astryx-live-region='polite']")?.textContent).toContain(
      "Anslutningstest för Vemsa Timrå: Tar emot jobb"
    )
  );
});

it("keeps one default when a slower answer to another edit arrives after the mark moved", async () => {
  const switchingOff = deferred<TranscriptionService>();
  update
    .mockReturnValueOnce(switchingOff.promise)
    .mockImplementationOnce(async () => ({ ...timra(), is_default: true }));
  renderSection([service({ is_default: true }), timra()]);

  // Switching the default off is sent while it still carries the mark.
  fireEvent.click(toggle("Vemsa Sundsvall"));
  await makeDefault("Vemsa Timrå");
  await waitFor(() => expect(row(/Vemsa Timrå/).textContent).toContain("Standard"));
  await act(async () => switchingOff.resolve(service({ is_enabled: false, is_default: true })));
  await settle();

  expect(row(/Vemsa Timrå/).textContent).toContain("Standard");
  expect(row(/Vemsa Sundsvall/).textContent).not.toContain("Standard");
  expect(toggle("Vemsa Sundsvall").checked).toBe(false);
});

it("leaves the default alone when the service being marked has left the list", async () => {
  const marking = deferred<TranscriptionService>();
  update.mockReturnValueOnce(marking.promise);
  const { reload } = renderSection([service(), timra()]);

  await makeDefault("Vemsa Timrå");
  await waitFor(() => expect(update).toHaveBeenCalled());
  // Read again: another administrator removed that service and marked this one.
  reload([service({ is_default: true })]);
  await act(async () => marking.resolve({ ...timra(), is_default: true }));
  await settle();

  expect(row(/Vemsa Sundsvall/).textContent).toContain("Standard");
  expect(screen.queryByRole("row", { name: /Vemsa Timrå/ })).toBeNull();
});

it("asks before switching off a service that spaces use, and keeps it on until confirmed", async () => {
  update.mockImplementation(async () => service({ space_count: 3, is_enabled: false }));
  renderSection([service({ space_count: 3 })]);

  fireEvent.click(toggle("Vemsa Sundsvall"));

  const confirm = await screen.findByRole("alertdialog");
  expect(within(confirm).getByText(/Den används i 3 ytor/)).toBeTruthy();
  expect(toggle("Vemsa Sundsvall").checked).toBe(true);
  expect(update).not.toHaveBeenCalled();

  fireEvent.click(within(confirm).getByRole("button", { name: "Stäng av" }));
  await waitFor(() => expect(update).toHaveBeenCalledWith("s1", { is_enabled: false }));
  await waitFor(() => expect(toggle("Vemsa Sundsvall").checked).toBe(false));
});

it("shows the check the server returns after a save, even one cleared by someone else", async () => {
  // Another administrator gave the service a new key meanwhile; the server
  // cleared its check, and a rename here must not bring the old one back.
  update.mockImplementation(async () => service({ name: "Vemsa Nord", last_check: null }));
  renderSection([service({ last_check: result("ready") })]);

  await editAndSave("Vemsa Sundsvall", () => type(/^Namn/, "Vemsa Nord"));

  const nord = await screen.findByRole("row", { name: /Vemsa Nord/ });
  expect(nord.textContent).toContain("Inte testad");
  expect(nord.textContent).not.toContain("Tar emot jobb");
});

it("drops a running check's answer once a save returns newer settings, and checks again", async () => {
  // The check tested the old address; another administrator moved the service
  // meanwhile, and the rename here answered with the cleared check.
  const running = deferred<Check>();
  const again = deferred<Check>();
  check.mockReturnValueOnce(running.promise).mockReturnValueOnce(again.promise);
  update.mockImplementation(async () =>
    service({ name: "Vemsa Nord", endpoint_url: "https://vemsa-nord.sundsvall.se" })
  );
  renderSection([service()]);

  choose("Vemsa Sundsvall", "Testa anslutningen");
  await editAndSave("Vemsa Sundsvall", () => type(/^Namn/, "Vemsa Nord"));
  const nord = await screen.findByRole("row", { name: /Vemsa Nord/ });
  await waitFor(() => expect(nord.textContent).toContain("Testar…"));

  await act(async () => running.resolve(result("ready")));
  await settle();
  expect(row(/Vemsa Nord/).textContent).not.toContain("Tar emot jobb");
  // The check it interrupted runs again, against the settings saved now.
  expect(check).toHaveBeenCalledTimes(2);
  await act(async () => again.resolve({ ...result("unavailable"), reason: "unreachable" }));
  await waitFor(() => expect(row(/Vemsa Nord/).textContent).toContain("Inte tillgänglig"));
});

it("removes a service after asking, and says which spaces lose it", async () => {
  renderSection([service({ space_count: 1 })]);

  choose("Vemsa Sundsvall", "Ta bort");
  const confirm = await screen.findByRole("alertdialog");
  expect(within(confirm).getByText(/Används i 1 yta\./)).toBeTruthy();
  list = [];
  fireEvent.click(within(confirm).getByRole("button", { name: "Ta bort" }));

  await waitFor(() => expect(remove).toHaveBeenCalledWith("s1"));
  expect(await screen.findByText("Ingen tjänst för ordtider och talare ansluten")).toBeTruthy();
});

it("keeps a failed list inside its section, with a way to try again", async () => {
  renderSection(null);

  expect(
    await screen.findByText("Tjänsterna för ordtider och talare kunde inte läsas in.")
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Anslut tjänst" })).toBeNull();
  list = [];
  fireEvent.click(screen.getByRole("button", { name: /^Försök igen/ }));
  expect(await screen.findByText("Ingen tjänst för ordtider och talare ansluten")).toBeTruthy();
});

it("sends a key only in the body of the save it was typed for, never in the address", async () => {
  update.mockImplementation(async () => service());
  renderSection([service()]);

  await editAndSave("Vemsa Sundsvall", () => type(/^API-nyckel/, "new-key"));

  await waitFor(() => expect(update).toHaveBeenCalledOnce());
  const [path, init] = api.PATCH.mock.calls[0]!;
  expect(init).toEqual({ params: { path: { connection_id: "s1" } }, body: { api_key: "new-key" } });
  expect(JSON.stringify([path, init.params])).not.toContain("new-key");
});
