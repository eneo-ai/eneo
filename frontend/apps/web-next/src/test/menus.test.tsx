// @vitest-environment jsdom
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { cleanup, screen } from "@testing-library/react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { menuFocus, openMenuOnRelease } from "./menus";
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

it("opens a menu on release when its focus comes frames after the open", async () => {
  // A layout change or a remount can move Astryx's focus a frame or more past the
  // open; the helper waits for the focus itself, not for a number of frames.
  renderInApp(<MoreMenu label="Fler åtgärder" items={[{ label: "Öppna", onClick: () => {} }]} />);
  const button = screen.getByRole("button", { name: "Fler åtgärder" });
  // Only the frames the open asks for (Astryx's focus) come three frames late.
  const frame = window.requestAnimationFrame.bind(window);
  let opening = true;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
    opening ? frame(() => frame(() => frame(callback))) : frame(callback)
  );
  button.addEventListener("click", () => queueMicrotask(() => (opening = false)));

  const menu = await openMenuOnRelease(button);

  expect(document.activeElement).toBe(menu);
});

it("opens a menu its button appeared before", async () => {
  // Astryx mounts a menu a render after its button. A test can reach the button in
  // between, as a loaded runner does: Astryx then opens the menu but never focuses it.
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", false);
  const name = "Fler åtgärder";
  const appeared = new Promise<HTMLElement>((resolve) => {
    const observer = new MutationObserver(() => {
      const button = screen.queryByRole("button", { name });
      if (!button) return;
      observer.disconnect();
      resolve(button);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
  const root = createRoot(document.body.appendChild(document.createElement("div")));
  onTestFinished(() => root.unmount());
  root.render(<MoreMenu label={name} items={[{ label: "Öppna", onClick: () => {} }]} />);

  const menu = await openMenuOnRelease(await appeared);

  expect(document.activeElement).toBe(menu);
});

describe("a menu that never gets focus", () => {
  it("leaves its wait to end with the test", () => {
    // Waited on as the helper does, for a menu that never takes focus, but not
    // awaited here, as a test that times out leaves it: its end releases the wait.
    void menuFocus("a-menu-that-never-opens").then(() => {});
  });

  it("does not hold the next test's renders back", () => {
    renderInApp(<MoreMenu label="Fler åtgärder" items={[{ label: "Öppna", onClick: () => {} }]} />);

    expect(screen.getByRole("button", { name: "Fler åtgärder" })).toBeTruthy();
  });
});
