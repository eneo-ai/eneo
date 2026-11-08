// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SessionExpiryDialog } from "./session-expiry";

const spies = vi.hoisted(() => ({
  extend: vi.fn(async () => {}),
  snapshot: vi.fn((): unknown => ({ status: "unknown" })),
  announce: vi.fn(),
  navigate: vi.fn()
}));
vi.mock("@/lib/api/refusal", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/refusal")>()),
  extendBrowserSession: spies.extend,
  getSessionSnapshot: spies.snapshot,
  resumeLoginPath: () => "/login?next=%2Fspaces%2Fx"
}));
vi.mock("@/lib/navigate-to", () => ({ navigateTo: spies.navigate }));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));

const NOW = new Date("2026-11-02T10:00:00Z").getTime();
const STAY = "Fortsätt vara inloggad";

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ now: NOW });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

const announced = () => spies.announce.mock.calls.map(([message]) => message as string);

it("opens two minutes before the end with focus on staying signed in", async () => {
  const { container } = renderInApp(<SessionExpiryDialog expiresAt={NOW + 121_000} />);
  expect(screen.queryByRole("dialog")).toBeNull();

  advance(1_000);

  const dialog = screen.getByRole("dialog", { name: "Din session går snart ut" });
  expect(dialog.getAttribute("aria-modal")).toBe("true");
  expect(document.activeElement).toBe(screen.getByRole("button", { name: STAY }));
  expect(dialog.textContent).toContain("Du loggas ut kl.");
  // The countdown is for the eye; a screen reader hears it at set points.
  const countdown = screen.getByText("2:00 kvar");
  expect(countdown.closest("[aria-hidden='true']")).not.toBeNull();
  expect(screen.getByRole("link", { name: "Logga ut" }).getAttribute("href")).toBe("/logout");
  expect(spies.announce).not.toHaveBeenCalled();
  vi.useRealTimers();
  await expectNoAxeViolations(container);
});

it("waits out a session longer than a timer can wait", () => {
  const timeout = vi.spyOn(window, "setTimeout");
  renderInApp(<SessionExpiryDialog expiresAt={NOW + 30 * 24 * 3_600_000} />);
  advance(25 * 24 * 3_600_000);
  expect(screen.queryByRole("dialog")).toBeNull();
  advance(5 * 24 * 3_600_000 - 120_000);
  expect(screen.getByRole("dialog", { name: "Din session går snart ut" })).toBeTruthy();
  // A browser runs a longer delay at once, over and over.
  const delays = timeout.mock.calls.map(([, delay]) => delay ?? 0);
  expect(Math.max(...delays)).toBeLessThanOrEqual(2 ** 31 - 1);
});

it("announces the time left at 60, 30 and 10 seconds, not every second", () => {
  renderInApp(<SessionExpiryDialog expiresAt={NOW + 120_000} />);
  advance(59_000);
  expect(spies.announce).not.toHaveBeenCalled();
  advance(1_000);
  advance(30_000);
  advance(20_000);
  advance(5_000);
  expect(announced()).toEqual([
    "Din session går ut om 60 sekunder.",
    "Din session går ut om 30 sekunder.",
    "Din session går ut om 10 sekunder."
  ]);
  expect(screen.getByText("0:05 kvar")).toBeTruthy();
});

it("stays signed in from the button or Esc, and keeps the button after a failure", async () => {
  spies.extend.mockRejectedValueOnce(new TypeError("Offline"));
  const view = renderInApp(<SessionExpiryDialog expiresAt={NOW + 60_000} />);

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: STAY }));
  });
  expect(spies.extend).toHaveBeenCalledTimes(1);
  expect(screen.getByText("Det gick inte att förlänga sessionen. Försök igen.")).toBeTruthy();
  expect(screen.getByRole("button", { name: STAY })).toBeTruthy();

  await act(async () => {
    fireEvent.keyDown(screen.getByRole("button", { name: STAY }), { key: "Escape" });
  });
  expect(spies.extend).toHaveBeenCalledTimes(2);
  expect(announced()).toContain("Du är fortsatt inloggad.");

  // The renewal publishes a later end, and the dialog closes.
  view.rerender(<SessionExpiryDialog expiresAt={Date.now() + 86_400_000} />);
  advance(1_000);
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("says when a renewal cannot move the end, at the session's maximum age, and closes", async () => {
  const view = renderInApp(<SessionExpiryDialog expiresAt={NOW + 60_000} />);
  spies.snapshot.mockReturnValue({ status: "bound", generation: "g", expiresAt: NOW + 60_500 });

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: STAY }));
  });
  // The server renewed up to its limit only: the session still ends within the warning.
  view.rerender(<SessionExpiryDialog expiresAt={NOW + 60_500} />);

  const dialog = screen.getByRole("dialog", { name: "Sessionen kan inte förlängas mer" });
  expect(dialog.textContent).toContain("Spara det du arbetar med");
  // Signing in again while this session is valid would only continue it: the
  // notice offers to close or to sign out, and signing in comes once it ends.
  expect(screen.queryByRole("button", { name: "Logga in igen" })).toBeNull();
  const button = screen.getByRole("button", { name: "Stäng" });
  expect(document.activeElement).toBe(button);
  expect(screen.getByRole("link", { name: "Logga ut" })).toBeTruthy();
  expect(announced()).toContain("Sessionen kan inte förlängas mer");
  expect(announced()).not.toContain("Du är fortsatt inloggad.");

  // The button's action settles after the click, so its update is awaited.
  await act(async () => {
    fireEvent.click(button);
  });
  advance(1_000);
  expect(spies.extend).toHaveBeenCalledTimes(1);
  expect(spies.navigate).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("still says when a session closed at its limit has ended, and signs in again to the same place", async () => {
  const view = renderInApp(<SessionExpiryDialog expiresAt={NOW + 60_000} />);
  spies.snapshot.mockReturnValue({ status: "bound", generation: "g", expiresAt: NOW + 60_500 });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: STAY }));
  });
  view.rerender(<SessionExpiryDialog expiresAt={NOW + 60_500} />);
  // Esc puts the notice away instead of asking for another renewal.
  await act(async () => {
    fireEvent.keyDown(screen.getByRole("button", { name: "Stäng" }), { key: "Escape" });
  });
  advance(1_000);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(spies.extend).toHaveBeenCalledTimes(1);

  advance(60_000);
  expect(screen.getByRole("dialog", { name: "Din session har gått ut" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Logga in igen" }));
  expect(spies.navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Fspaces%2Fx");
});

it("keeps the page at the end and offers to sign in again to the same place", () => {
  renderInApp(<SessionExpiryDialog expiresAt={NOW + 5_000} />);
  const button = screen.getByRole("button", { name: STAY });

  advance(5_000);

  expect(screen.getByRole("dialog", { name: "Din session har gått ut" })).toBeTruthy();
  // The same control, renamed, so focus stays where it was.
  expect(screen.getByRole("button", { name: "Logga in igen" })).toBe(button);
  expect(document.activeElement).toBe(button);
  expect(screen.queryByRole("link", { name: "Logga ut" })).toBeNull();
  expect(announced()).toContain("Din session har gått ut");
  fireEvent.click(button);
  expect(spies.extend).not.toHaveBeenCalled();
  expect(spies.navigate).toHaveBeenCalledExactlyOnceWith("/login?next=%2Fspaces%2Fx");
});

it("lets Esc put away a notice that opened as a warning and ran out, without renewing", () => {
  renderInApp(<SessionExpiryDialog expiresAt={NOW + 5_000} />);
  advance(5_000);
  fireEvent.keyDown(screen.getByRole("button", { name: "Logga in igen" }), { key: "Escape" });
  advance(1_000);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(spies.extend).not.toHaveBeenCalled();
});

it("lets Esc put the expired notice away so the page can be read and copied", () => {
  renderInApp(<SessionExpiryDialog expiresAt={NOW} />);
  expect(screen.getByRole("dialog", { name: "Din session har gått ut" })).toBeTruthy();
  fireEvent.keyDown(screen.getByRole("button", { name: "Logga in igen" }), { key: "Escape" });
  advance(1_000);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(spies.extend).not.toHaveBeenCalled();
});

it.each([60_000, 120_000])(
  "gives a %i ms session half its life before warning, and a renewal closes the warning",
  async (lifetime) => {
    const view = renderInApp(
      <SessionExpiryDialog expiresAt={NOW + lifetime} lifetime={lifetime} />
    );
    // Not at sign-in: the warning takes at most half of a short session.
    expect(screen.queryByRole("dialog")).toBeNull();
    advance(lifetime / 2 - 1_000);
    expect(screen.queryByRole("dialog")).toBeNull();
    advance(1_000);
    await act(async () => {
      fireEvent.keyDown(screen.getByRole("button", { name: STAY }), { key: "Escape" });
    });
    expect(spies.extend).toHaveBeenCalledOnce();

    view.rerender(<SessionExpiryDialog expiresAt={Date.now() + lifetime} lifetime={lifetime} />);
    advance(1_000);
    expect(screen.queryByRole("dialog")).toBeNull();
    advance(lifetime / 2 - 2_000);
    expect(screen.queryByRole("dialog")).toBeNull();
    advance(1_000);
    expect(screen.getByRole("dialog", { name: "Din session går snart ut" })).toBeTruthy();
  }
);

it("warns a 30 s session 20 s before its end, the least time WCAG allows", () => {
  renderInApp(<SessionExpiryDialog expiresAt={NOW + 30_000} lifetime={30_000} />);
  advance(9_000);
  expect(screen.queryByRole("dialog")).toBeNull();
  advance(1_000);
  expect(screen.getByRole("dialog", { name: "Din session går snart ut" })).toBeTruthy();
  expect(screen.getByText("0:20 kvar")).toBeTruthy();
});

it("opens at once on a ten-minute session reopened with 30 s left", () => {
  renderInApp(<SessionExpiryDialog expiresAt={NOW + 30_000} lifetime={600_000} />);
  expect(screen.getByRole("dialog", { name: "Din session går snart ut" })).toBeTruthy();
  expect(screen.getByText("0:30 kvar")).toBeTruthy();
});
