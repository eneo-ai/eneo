// @vitest-environment jsdom
import { createRoute, Outlet, type AnyRootRoute } from "@tanstack/react-router";
import { act, screen, waitFor } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, expectTypeOf, it, vi } from "vitest";
import { SpaceFrame } from "@/features/spaces/frame/space-frame";
import { readCached } from "@/lib/api/query";
import { renderWithRouter } from "@/test/router";
import type * as NextNavigation from "./navigation";
import * as navigation from "./navigation.tanstack";

// SpaceFrame (and anything else) reads the seam: here, the TanStack one.
vi.mock("@/lib/navigation", () => import("@/lib/navigation.tanstack"));
vi.mock("@/features/spaces/frame/space-header", () => ({
  SpaceHeader: () => <p>Space header</p>
}));

let finishSlow: () => void;
let seam: ReturnType<typeof navigation.useRouter>;

beforeEach(() => {
  finishSlow = () => {};
});

afterEach(() => vi.restoreAllMocks());

/** `/slow` (and `/spaces/$id/overview`) wait for `finishSlow()`. */
const slowLoader = () => new Promise<void>((resolve) => (finishSlow = resolve));

const routes = (root: AnyRootRoute) => [
  createRoute({ getParentRoute: () => root, path: "/a", component: () => <h1>Page A</h1> }),
  createRoute({ getParentRoute: () => root, path: "/slow", loader: slowLoader, component: Outlet }),
  createRoute({
    getParentRoute: () => root,
    path: "/spaces/$spaceId/overview",
    loader: slowLoader,
    component: Outlet
  })
];

function Location() {
  const router = navigation.useRouter();
  useEffect(() => {
    seam = router;
  }, [router]);
  const tab = navigation.useSearchParams().get("tab");
  return <p data-testid="location">{`${navigation.usePathname()} ${tab ?? "-"}`}</p>;
}

const location = () => screen.getByTestId("location").textContent;

it("is typed as the Next navigation", () => {
  expectTypeOf(navigation.useRouter).toEqualTypeOf<typeof NextNavigation.useRouter>();
  expectTypeOf(navigation.usePathname).toEqualTypeOf<typeof NextNavigation.usePathname>();
  expectTypeOf(navigation.useSearchParams).toEqualTypeOf<typeof NextNavigation.useSearchParams>();
  expectTypeOf(navigation.replaceUrl).toEqualTypeOf<typeof NextNavigation.replaceUrl>();
});

describe("while the next page loads", () => {
  it("reports the page on screen, not the one loading", async () => {
    const { router } = await renderWithRouter(<Location />, { route: "/a?tab=x", routes });

    act(() => seam.push("/slow"));
    await act(async () => {});
    expect(router.state.location.pathname).toBe("/slow");
    expect(location()).toBe("/a x");

    await act(async () => finishSlow());
    expect(location()).toBe("/slow -");
  });

  it("gives the next page its own address from its first render", async () => {
    const firstRender: string[] = [];
    function Destination() {
      const pathname = navigation.usePathname();
      const tab = navigation.useSearchParams().get("tab");
      // A page that starts its tab from the URL keeps what it read first.
      const [initial] = useState(() => `${pathname} ${tab}`);
      firstRender.push(initial);
      return null;
    }
    await renderWithRouter(<Location />, {
      route: "/a?tab=old",
      routes: (root) => [
        ...routes(root),
        createRoute({ getParentRoute: () => root, path: "/b", component: Destination })
      ]
    });

    await act(async () => seam.push("/b?tab=new"));

    expect(firstRender[0]).toBe("/b new");
    expect(location()).toBe("/b new");
  });

  it("keeps the space's chrome", async () => {
    const { router } = await renderWithRouter(<SpaceFrame>{null}</SpaceFrame>, {
      route: "/spaces/s1/chat",
      routes
    });
    expect(screen.queryByText("Space header")).toBeNull();

    act(() => void router.navigate({ href: "/spaces/s1/overview" }));
    await act(async () => {});
    expect(screen.queryByText("Space header")).toBeNull();

    await act(async () => finishSlow());
    expect(screen.getByText("Space header")).toBeTruthy();
  });
});

it("returns one query object per query", async () => {
  const seen: URLSearchParams[] = [];
  function Probe() {
    const [, setCount] = useState(0);
    seen.push(navigation.useSearchParams() as URLSearchParams);
    return (
      <button type="button" onClick={() => setCount((count) => count + 1)}>
        Render
      </button>
    );
  }
  await renderWithRouter(<Probe />, { route: "/a?tab=x" });

  act(() => screen.getByRole("button").click());
  expect(seen.at(-1)).toBe(seen.at(-2));

  await act(async () => navigation.replaceUrl("/a?tab=y"));
  expect(seen.at(-1)?.get("tab")).toBe("y");
  expect(seen.at(-1)).not.toBe(seen.at(-2));
});

describe("useSpaceSegments", () => {
  it.each([
    // As in the address bar, like the Next implementation.
    ["/spaces/s1/assistants/a%201/edit", ["assistants", "a%201", "edit"]],
    ["/spaces/s1", []],
    ["/spaces/s1/knowledge/", ["knowledge"]]
  ])("reads %s as the segments below the space", async (route, segments) => {
    let read: string[] = [];
    function Probe() {
      read = navigation.useSpaceSegments();
      return null;
    }
    await renderWithRouter(<Probe />, { route });

    expect(read).toEqual(segments);
  });
});

describe("scroll and history", () => {
  async function renderPanel(route: string) {
    const result = await renderWithRouter(
      <main id="main-content">
        <Location />
      </main>,
      { route, routes }
    );
    const panel = document.getElementById("main-content")!;
    panel.scrollTo = vi.fn();
    return { ...result, panel };
  }

  it("scrolls the page panel to the top after push", async () => {
    const { panel, router } = await renderPanel("/a?tab=x");
    const entries = router.history.length;

    await act(async () => seam.push("/a"));

    await waitFor(() =>
      expect(panel.scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 0 }))
    );
    expect(router.history.length).toBe(entries + 1);
  });

  it("keeps the scroll position and the history on replace without scroll", async () => {
    const { panel, router } = await renderPanel("/a");
    const entries = router.history.length;

    await act(async () => seam.replace("/a?tab=x", { scroll: false }));

    expect(location()).toBe("/a x");
    expect(panel.scrollTo).not.toHaveBeenCalled();
    expect(router.history.length).toBe(entries);
  });

  it("updates the address in place with replaceUrl, relative to the current one", async () => {
    const { panel, router } = await renderPanel("/a?tab=x");
    const entries = router.history.length;

    await act(async () => navigation.replaceUrl("?tab=y"));

    expect(location()).toBe("/a y");
    expect(router.state.location.href).toBe("/a?tab=y");
    expect(panel.scrollTo).not.toHaveBeenCalled();
    expect(router.history.length).toBe(entries);
  });

  it("scrolls to a hash target only when the navigation may scroll", async () => {
    await renderPanel("/a");
    const target = document.createElement("p");
    target.id = "target";
    document.body.append(target);
    target.scrollIntoView = vi.fn();

    await act(async () => navigation.replaceUrl("/a?tab=y#target"));
    await act(async () => seam.replace("/a?tab=z#target", { scroll: false }));
    await act(async () => seam.push("/a?tab=w#target", { scroll: false }));
    expect(target.scrollIntoView).not.toHaveBeenCalled();

    await act(async () => seam.push("/a#target"));
    await waitFor(() => expect(target.scrollIntoView).toHaveBeenCalledTimes(1));
    target.remove();
  });

  it("refuses an address on another origin", async () => {
    await renderPanel("/a");

    expect(() => navigation.replaceUrl("https://example.org/a")).toThrow(/origin/);
  });

  it("keeps section history state through replacement and browser Back/Forward", async () => {
    const { panel, router } = await renderPanel("/a");
    const entries = router.history.length;
    await act(async () =>
      navigation.pushUrl("?tab=x#target", {
        state: { settingsSectionFromIndex: true }
      })
    );
    expect(router.history.length).toBe(entries + 1);
    expect(navigation.readUrlState().settingsSectionFromIndex).toBe(true);
    await act(async () => navigation.replaceUrl("?tab=y#target"));
    expect(navigation.readUrlState().settingsSectionFromIndex).toBe(true);
    expect(router.state.location.hash).toBe("target");
    expect(router.history.length).toBe(entries + 1);
    expect(panel.scrollTo).not.toHaveBeenCalled();
    await act(async () => router.history.back());
    expect(location()).toBe("/a -");
    expect(navigation.readUrlState().settingsSectionFromIndex).toBeUndefined();
    await act(async () => router.history.forward());
    expect(location()).toBe("/a y");
    expect(navigation.readUrlState().settingsSectionFromIndex).toBe(true);
    vi.mocked(panel.scrollTo).mockClear();
    await act(async () =>
      navigation.replaceUrl("?tab=y#target", {
        state: { settingsSectionFromIndex: false }
      })
    );
    expect(navigation.readUrlState().settingsSectionFromIndex).toBe(false);
    expect(panel.scrollTo).not.toHaveBeenCalled();
    expect(() => navigation.pushUrl("https://example.org/a")).toThrow(/origin/);
    expect(() => navigation.pushUrl("javascript:alert(1)")).toThrow(/origin/);
  });
});

describe("replaceUrl on the same route", () => {
  it("commits without waiting for a refetch in flight", async () => {
    const me = { queryKey: ["users", "me"], queryFn: async () => "Anna" };
    const { queryClient } = await renderWithRouter(<Location />, {
      route: "/page",
      routes: (root) => [
        createRoute({
          getParentRoute: () => root,
          path: "/page",
          beforeLoad: ({ context }) => readCached(context.queryClient, me),
          component: () => null
        })
      ]
    });
    // A finished job invalidated the session's user; the backend has not
    // answered the refetch yet.
    await queryClient.invalidateQueries({ queryKey: me.queryKey, refetchType: "none" });
    void queryClient.query({ ...me, queryFn: () => new Promise<string>(() => {}) });
    expect(queryClient.getQueryState(me.queryKey)?.fetchStatus).toBe("fetching");

    await act(async () => navigation.replaceUrl("/page?tab=b"));

    expect(location()).toBe("/page b");
  });

  it("keeps the page mounted, as a streaming chat needs", async () => {
    let mounts = 0;
    function Chat() {
      const [tokens, setTokens] = useState(0);
      useEffect(() => {
        mounts++;
      }, []);
      const sessionId = navigation.useSearchParams().get("session_id");
      return (
        <button type="button" onClick={() => setTokens((count) => count + 1)}>
          {`${tokens} tokens in ${sessionId ?? "a new conversation"}`}
        </button>
      );
    }
    await renderWithRouter(null, {
      route: "/chat",
      routes: (root) => [
        createRoute({ getParentRoute: () => root, path: "/chat", component: Chat })
      ]
    });
    act(() => screen.getByRole("button").click());

    await act(async () => navigation.replaceUrl("/chat?session_id=s1"));

    expect(screen.getByRole("button").textContent).toBe("1 tokens in s1");
    expect(mounts).toBe(1);
  });
});

it("throws before createAppRouter binds a router", async () => {
  vi.resetModules();
  const fresh = await import("./navigation.tanstack");

  expect(() => fresh.replaceUrl("/a")).toThrow(/createAppRouter/);
});
