// @vitest-environment jsdom
import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";
import * as navigation from "./navigation";
import type { AppRouter, ReadonlySearchParams } from "./navigation";

const pathname = vi.hoisted(() => ({ current: "/" }));
vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  usePathname: () => pathname.current
}));

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useSpaceSegments", () => {
  it.each([
    ["/spaces/s1", []],
    ["/spaces/s1/knowledge/collections/c1", ["knowledge", "collections", "c1"]],
    ["/spaces/personal/chat/", ["chat"]]
  ])("reads %s as the segments below the space", (path, segments) => {
    pathname.current = path;
    expect(navigation.useSpaceSegments()).toEqual(segments);
  });
});

describe("replaceUrl", () => {
  it("replaces the current history entry with the address", () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    navigation.replaceUrl("/a?tab=x");
    expect(replaceState).toHaveBeenCalledWith(null, "", "/a?tab=x");
    expect(window.location.pathname + window.location.search).toBe("/a?tab=x");
  });
});

it("exposes only the API the TanStack implementation offers", () => {
  // Checked by tsc (`bun run check`). That Next's hooks satisfy these types
  // is checked where navigation.ts assigns them.
  expectTypeOf<ReturnType<typeof navigation.useRouter>>().toEqualTypeOf<AppRouter>();
  expectTypeOf<AppRouter>().not.toHaveProperty("prefetch");
  expectTypeOf<AppRouter>().not.toHaveProperty("forward");
  expectTypeOf<
    ReturnType<typeof navigation.useSearchParams>
  >().toEqualTypeOf<ReadonlySearchParams>();
  expectTypeOf<ReadonlySearchParams>().not.toHaveProperty("set");
  expectTypeOf<ReturnType<typeof navigation.usePathname>>().toEqualTypeOf<string>();
});
