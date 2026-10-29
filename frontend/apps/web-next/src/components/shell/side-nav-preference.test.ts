import { expect, it } from "vitest";
import { readSideNavCollapsedCookie } from "./side-nav-preference";

it.each([
  ["a=1; eneo_sidenav_collapsed=1", true],
  ["eneo_sidenav_collapsed=0", false],
  ["a=1", false]
])("reads the stored sidebar preference from %s", (cookie, collapsed) => {
  expect(readSideNavCollapsedCookie(cookie)).toBe(collapsed);
});
