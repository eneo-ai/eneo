import { expect, it } from "vitest";
import { readSideNavCollapsedCookie } from "./side-nav-preference";

it.each([
  ["a=1; eneo_sidenav_collapsed=1", true],
  ["eneo_sidenav_collapsed=0", false],
  // Never chosen: the nav follows the width (side-nav.tsx).
  ["a=1", undefined],
  ["", undefined]
])("reads the stored sidebar preference from %s", (cookie, collapsed) => {
  expect(readSideNavCollapsedCookie(cookie)).toBe(collapsed);
});
