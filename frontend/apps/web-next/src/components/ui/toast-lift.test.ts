import { describe, expect, it } from "vitest";
import { type Box, liftToClear } from "./toast-lift";

// Where sonner's toasts rest (a 73 px toast): 24 px from the bottom right of a
// 1280 × 800 window, and full width 16 px from the bottom of a 390 × 844 phone.
const onDesktop = (target: Box) =>
  liftToClear({ left: 900, right: 1256, top: 703, bottom: 776 }, target, {
    width: 1280,
    height: 800
  });
const onPhone = (target: Box) =>
  liftToClear({ left: 16, right: 374, top: 755, bottom: 828 }, target, {
    width: 390,
    height: 844
  });

describe("liftToClear", () => {
  it("leaves the toasts at rest while they cover none of the focused element", () => {
    // A dialog's primary button left of them, and the chat's text field above them.
    expect(onDesktop({ left: 804, right: 872, top: 748, bottom: 784 })).toBe(0);
    expect(onPhone({ left: 28, right: 362, top: 682, bottom: 728 })).toBe(0);
  });

  it("raises them to just above an element they would cover", () => {
    // A save bar's button in the corner: their lower edge goes 8 px above it.
    expect(onDesktop({ left: 1125, right: 1256, top: 752, bottom: 788 })).toBe(32);
    // The docked chat composer's Send button on a phone.
    expect(onPhone({ left: 318, right: 362, top: 736, bottom: 780 })).toBe(100);
  });

  it("keeps clear of the focus outline around the element", () => {
    // 4 px left of them: its outline (2 px at a 3 px offset) would be under them.
    expect(onDesktop({ left: 800, right: 896, top: 720, bottom: 760 })).toBe(64);
  });

  it("counts only what shows of the element", () => {
    // Below the window, and scrolled up so only its lower part shows, above them.
    expect(onPhone({ left: 40, right: 350, top: 900, bottom: 944 })).toBe(0);
    expect(onPhone({ left: 40, right: 350, top: -600, bottom: 40 })).toBe(0);
  });

  it("stays on screen: an element taller than the room above them stays mostly in view", () => {
    // A focused scrolling region: clearing it would lift the toasts off the top.
    expect(onPhone({ left: 0, right: 390, top: 40, bottom: 800 })).toBe(0);
  });
});
