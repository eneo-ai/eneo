// @vitest-environment jsdom
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import { onlineManager } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ConnectionAnnouncer, ConnectionBanner } from "./connection-banner";

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
});

/** What Astryx's polite live region has said (useAnnounce). */
const announced = () =>
  [...document.querySelectorAll("[aria-live]")].map((region) => region.textContent).join(" ");

const goOffline = () => act(() => void window.dispatchEvent(new Event("offline")));
const goOnline = () => act(() => void window.dispatchEvent(new Event("online")));

/** The banner as a page shows it, with the shell's one announcer. */
const Shown = () => (
  <>
    <ConnectionAnnouncer />
    <ConnectionBanner />
  </>
);

describe("ConnectionBanner", () => {
  it("shows nothing and says nothing while the browser is online", () => {
    renderInApp(<Shown />);
    expect(screen.queryByText("Du är offline")).toBeNull();
    expect(announced()).not.toContain("offline");
  });

  it("says once, politely, that the connection is lost and what that means", async () => {
    const { container } = renderInApp(<Shown />);
    goOffline();
    const description = screen.getByText(
      "Frågor kan inte skickas och ändringar kan inte sparas förrän du är uppkopplad igen."
    );
    expect(container.textContent).toContain("Du är offline");
    // A lasting state, not an alert read out again on every mount.
    expect(description.closest('[role="alert"], [role="status"], [aria-live]')).toBeNull();
    await waitFor(() => expect(announced()).toContain("Du är offline"));
    await expectNoAxeViolations(container);
  });

  it("goes away and says so when the connection is back", async () => {
    const { container } = renderInApp(<Shown />);
    goOffline();
    goOnline();
    expect(container.textContent).toBe("");
    await waitFor(() => expect(announced()).toContain("Du är uppkopplad igen"));
  });

  it("is said once however many pages show it", async () => {
    renderInApp(
      <>
        <ConnectionAnnouncer />
        <ConnectionBanner />
        <ConnectionBanner />
      </>
    );
    goOffline();
    await waitFor(() => expect(announced()).toContain("Du är offline"));
    expect(announced().match(/Du är offline/g)).toHaveLength(1);
  });
});
