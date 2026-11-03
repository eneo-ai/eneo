// @vitest-environment jsdom
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { openMenuOnRelease } from "./menus";
import { renderInApp } from "./render";

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

it("opens a menu on release however late the next animation frame comes", async () => {
  // Astryx moves focus into an opened menu on the next animation frame. On a
  // loaded runner that frame can come later than a wall-clock wait allows.
  const frame = window.requestAnimationFrame.bind(window);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
    frame((time) => setTimeout(() => callback(time), 1_200))
  );
  renderInApp(<MoreMenu label="Fler åtgärder" items={[{ label: "Öppna", onClick: () => {} }]} />);

  const menu = await openMenuOnRelease(screen.getByRole("button", { name: "Fler åtgärder" }));

  expect(document.activeElement).toBe(menu);
});
