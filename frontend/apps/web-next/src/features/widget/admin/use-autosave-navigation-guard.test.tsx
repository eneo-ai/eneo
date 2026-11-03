// @vitest-environment jsdom
import { createBrowserHistory, createRoute, type AnyRootRoute } from "@tanstack/react-router";
import { act, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderWithRouter } from "@/test/router";
import { useAutosaveNavigationGuard, type GuardedAutosave } from "./use-autosave-navigation-guard";

function store(overrides: Partial<GuardedAutosave> = {}) {
  let resolveFlush: () => void = () => {};
  const autosave: GuardedAutosave & { settle: (saved: boolean) => void } = {
    unsaved: true,
    stranded: false,
    flush: vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveFlush = resolve;
        })
    ),
    settle(saved) {
      autosave.unsaved = !saved;
      resolveFlush();
    },
    ...overrides
  };
  return autosave;
}
function Guard({ autosave }: { autosave: GuardedAutosave }) {
  useAutosaveNavigationGuard(autosave);
  return null;
}
const routes = (root: AnyRootRoute) =>
  ["/editor", "/elsewhere"].map((path) => createRoute({ getParentRoute: () => root, path }));
afterEach(() => vi.restoreAllMocks());

it("holds a route transition until the pending save lands, preserving its fragment", async () => {
  const autosave = store();
  const { router } = await renderWithRouter(<Guard autosave={autosave} />, {
    route: "/editor",
    routes
  });
  act(() => {
    void router.navigate({ href: "/elsewhere#details" });
  });
  await waitFor(() => expect(autosave.flush).toHaveBeenCalledTimes(1));
  expect(router.state.location.pathname).toBe("/editor");
  await act(() => autosave.settle(true));
  await waitFor(() => expect(router.state.location.href).toBe("/elsewhere#details"));
});

it("keeps the editor and its draft when saving fails", async () => {
  const autosave = store();
  const { router } = await renderWithRouter(<Guard autosave={autosave} />, {
    route: "/editor",
    routes
  });
  act(() => {
    void router.navigate({ href: "/elsewhere" });
  });
  await waitFor(() => expect(autosave.flush).toHaveBeenCalled());
  await act(() => autosave.settle(false));
  expect(router.state.location.pathname).toBe("/editor");
});

it("asks before abandoning edits that cannot be saved", async () => {
  const autosave = store({ stranded: true });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const { router } = await renderWithRouter(<Guard autosave={autosave} />, {
    route: "/editor",
    routes
  });
  await act(async () => {
    void router.navigate({ href: "/elsewhere" });
  });
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(router.state.location.pathname).toBe("/editor");
  expect(autosave.flush).not.toHaveBeenCalled();
  confirm.mockReturnValue(true);
  await act(async () => {
    void router.navigate({ href: "/elsewhere" });
  });
  await waitFor(() => expect(router.state.location.pathname).toBe("/elsewhere"));
});

it("preserves browser back instead of adding a replacement history entry", async () => {
  const autosave = store({ unsaved: false });
  window.history.replaceState(null, "", "/elsewhere");
  const history = createBrowserHistory();
  const view = await renderWithRouter(<Guard autosave={autosave} />, { history, routes });
  try {
    await act(() => view.router.navigate({ href: "/editor" }));
    autosave.unsaved = true;
    view.rerender(<Guard autosave={autosave} />);
    const entries = history.length;
    await act(async () => history.back());
    await waitFor(() => expect(autosave.flush).toHaveBeenCalled());
    expect(view.router.state.location.pathname).toBe("/editor");
    await act(() => autosave.settle(true));
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/elsewhere"));
    expect(history.length).toBe(entries);
    await act(async () => history.forward());
    await waitFor(() => expect(view.router.state.location.pathname).toBe("/editor"));
  } finally {
    view.unmount();
    history.destroy();
  }
});
