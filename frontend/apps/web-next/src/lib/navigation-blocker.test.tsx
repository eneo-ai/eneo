// @vitest-environment jsdom
import { createBrowserHistory, createRoute, type AnyRootRoute } from "@tanstack/react-router";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import {
  LeaveConfirmation,
  type LeaveConfirmationHandle
} from "@/components/composites/leave-confirmation";
import { expect, it, vi } from "vitest";
import { renderWithRouter } from "@/test/router";
import Link from "./link";
import { pushUrl, replaceUrl, useLeaveConfirmation, useRouter } from "./navigation";

vi.unmock("@/lib/link");

function Editor({ initialDirty = true }: { initialDirty?: boolean }) {
  const [dirty, setDirty] = useState(initialDirty);
  const guard = useLeaveConfirmation(dirty);
  const router = useRouter();
  return (
    <>
      <output>{guard.blocked ? "Blocked" : "Idle"}</output>
      <button onClick={() => setDirty(!dirty)}>Toggle dirty</button>
      <button onClick={guard.stay}>Stay</button>
      <button onClick={guard.leave}>Leave</button>
      <button onClick={() => router.push("/b?tab=x#details")}>Push</button>
      <button onClick={() => router.replace("/b?tab=x#details")}>Replace</button>
      <button onClick={() => pushUrl("/a?tab=x")}>Update URL</button>
      <button onClick={() => replaceUrl("/a?session_id=saved", { ignoreBlocker: true })}>
        Session metadata
      </button>
      <Link href="/b?tab=x#details">Page B</Link>
      <Link href="/a#details">Section</Link>
      <Link href="https://example.test/">External</Link>
    </>
  );
}
const routes = (root: AnyRootRoute) =>
  ["/a", "/b"].map((path) =>
    createRoute({
      getParentRoute: () => root,
      path,
      component: () => <h1>{path}</h1>
    })
  );
const click = async (name: string) =>
  act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
const blocked = () => screen.getByRole("status").textContent;

it("shares the leave decision with an in-place reset and never runs it on teardown", async () => {
  const reset = vi.fn();
  function LocalEditor() {
    const guard = useRef<LeaveConfirmationHandle>(null);
    return (
      <>
        <LeaveConfirmation ref={guard} active />
        <button onClick={() => guard.current?.confirm(reset)}>Reset editor</button>
      </>
    );
  }
  const { router, unmount } = await renderWithRouter(<LocalEditor />, { route: "/a", routes });
  await click("Reset editor");
  expect(screen.getByRole("alertdialog")).toBeTruthy();
  expect(reset).not.toHaveBeenCalled();
  await click("Avbryt");
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(reset).not.toHaveBeenCalled();
  await click("Reset editor");
  await click("Lämna utan att spara");
  expect(reset).toHaveBeenCalledTimes(1);
  await click("Reset editor");
  await act(async () => {
    void router.navigate({ href: "/b" });
  });
  await click("Lämna utan att spara");
  await waitFor(() => expect(router.state.location.pathname).toBe("/b"));
  expect(reset).toHaveBeenCalledTimes(1);
  await click("Reset editor");
  unmount();
  expect(reset).toHaveBeenCalledTimes(1);
});

it("lets an inactive editor follow links", async () => {
  const { router } = await renderWithRouter(<Editor initialDirty={false} />, {
    route: "/a",
    routes
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("link", { name: "Page B" }));
  });
  await waitFor(() => expect(router.state.location.href).toBe("/b?tab=x#details"));
  expect(blocked()).toBe("Idle");
});

it("holds a link until Stay or Leave and preserves the full destination", async () => {
  const { router } = await renderWithRouter(<Editor />, { route: "/a", routes });
  await act(async () => {
    fireEvent.click(screen.getByRole("link", { name: "Page B" }));
  });
  await waitFor(() => expect(blocked()).toBe("Blocked"));
  expect(router.state.location.href).toBe("/a");
  await click("Stay");
  expect(blocked()).toBe("Idle");
  expect(router.state.location.href).toBe("/a");
  await act(async () => {
    fireEvent.click(screen.getByRole("link", { name: "Page B" }));
  });
  await waitFor(() => expect(blocked()).toBe("Blocked"));
  await click("Leave");
  await waitFor(() => expect(router.state.location.href).toBe("/b?tab=x#details"));
  expect(blocked()).toBe("Idle");
});

it.each(["Push", "Replace", "Update URL"])(
  "holds %s through the same router owner",
  async (action) => {
    const { router } = await renderWithRouter(<Editor />, { route: "/a", routes });
    await click(action);
    await waitFor(() => expect(blocked()).toBe("Blocked"));
    expect(router.state.location.href).toBe("/a");
    await click("Leave");
    await waitFor(() =>
      expect(router.state.location.href).toBe(
        action === "Update URL" ? "/a?tab=x" : "/b?tab=x#details"
      )
    );
  }
);

it("can cancel and confirm Back and Forward without corrupting the history", async () => {
  window.history.replaceState(null, "", "/a");
  const history = createBrowserHistory();
  const { router, unmount } = await renderWithRouter(<Editor initialDirty={false} />, {
    history,
    routes
  });
  try {
    await click("Push");
    await waitFor(() => expect(router.state.location.pathname).toBe("/b"));
    await click("Toggle dirty");
    await act(async () => {
      router.history.back();
    });
    await waitFor(() => expect(blocked()).toBe("Blocked"));
    await click("Stay");
    expect(router.state.location.pathname).toBe("/b");
    await waitFor(() => expect(window.location.pathname).toBe("/b"));
    await act(async () => {
      router.history.back();
    });
    await waitFor(() => expect(blocked()).toBe("Blocked"));
    await click("Leave");
    await waitFor(() => expect(router.state.location.pathname).toBe("/a"));
    await act(async () => {
      router.history.forward();
    });
    await waitFor(() => expect(blocked()).toBe("Blocked"));
    await click("Stay");
    expect(router.state.location.pathname).toBe("/a");
    await waitFor(() => expect(window.location.pathname).toBe("/a"));
    await act(async () => {
      router.history.forward();
    });
    await waitFor(() => expect(blocked()).toBe("Blocked"));
    await click("Leave");
    await waitFor(() => expect(router.state.location.href).toBe("/b?tab=x#details"));
  } finally {
    unmount();
    history.destroy();
  }
});

it("allows a fragment on the same page without abandoning edits", async () => {
  const { router } = await renderWithRouter(<Editor />, { route: "/a", routes });
  await act(async () => {
    fireEvent.click(screen.getByRole("link", { name: "Section" }));
  });
  await waitFor(() => expect(router.state.location.hash).toBe("details"));
  expect(blocked()).toBe("Idle");
});

it("updates the displayed conversation's metadata without consuming departure protection", async () => {
  const { router } = await renderWithRouter(<Editor />, { route: "/a", routes });
  await click("Session metadata");
  await waitFor(() => expect(router.state.location.href).toBe("/a?session_id=saved"));
  expect(blocked()).toBe("Idle");
  await click("Push");
  await waitFor(() => expect(blocked()).toBe("Blocked"));
  await click("Stay");
  expect(router.state.location.href).toBe("/a?session_id=saved");
});

it("does not let late session metadata supersede an accepted loading departure", async () => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => (release = resolve));
  const { router } = await renderWithRouter(<Editor />, {
    route: "/a",
    routes: (root) => [
      createRoute({ getParentRoute: () => root, path: "/a", component: () => <h1>Page A</h1> }),
      createRoute({
        getParentRoute: () => root,
        path: "/b",
        loader: () => pending,
        component: () => <h1>Page B</h1>
      })
    ]
  });
  try {
    await click("Push");
    await waitFor(() => expect(blocked()).toBe("Blocked"));
    await click("Leave");
    await waitFor(() => expect(router.state.isLoading).toBe(true));
    await click("Session metadata");
    expect(router.state.location.pathname).toBe("/b");
    release();
    await screen.findByRole("heading", { name: "Page B" });
    expect(router.state.location.href).toBe("/b?tab=x#details");
  } finally {
    release();
  }
});

it("leaves modified and external link clicks to the browser", async () => {
  const { router } = await renderWithRouter(<Editor />, { route: "/a", routes });
  const preventBrowserNavigation = (event: Event) => event.preventDefault();
  window.addEventListener("click", preventBrowserNavigation);
  try {
    await act(async () => {
      fireEvent.click(screen.getByRole("link", { name: "Page B" }), { ctrlKey: true });
      fireEvent.click(screen.getByRole("link", { name: "Page B" }), { metaKey: true });
      fireEvent.click(screen.getByRole("link", { name: "External" }));
    });
    expect(blocked()).toBe("Idle");
    expect(router.state.location.href).toBe("/a");
  } finally {
    window.removeEventListener("click", preventBrowserNavigation);
  }
});

it("keeps browser unload protection only while edits are unsaved and removes it on unmount", async () => {
  window.history.replaceState(null, "", "/a");
  const history = createBrowserHistory();
  const { unmount } = await renderWithRouter(<Editor />, { history, routes });
  const unload = () => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  };
  try {
    expect(unload()).toBe(true);
    await click("Toggle dirty");
    expect(unload()).toBe(false);
    await click("Toggle dirty");
    expect(unload()).toBe(true);
    unmount();
    expect(unload()).toBe(false);
  } finally {
    unmount();
    history.destroy();
  }
});

it.each([false, true])(
  "confirms a departure once, then re-arms after its loader settles (failure: %s)",
  async (fail) => {
    window.history.replaceState(null, "", "/a");
    const history = createBrowserHistory();
    let release!: () => void;
    const pending = new Promise<void>((resolve) => (release = resolve));
    const { router, unmount } = await renderWithRouter(<Editor />, {
      history,
      routes: (root) => [
        createRoute({ getParentRoute: () => root, path: "/a", component: () => <h1>Page A</h1> }),
        createRoute({
          getParentRoute: () => root,
          path: "/b",
          loader: async () => {
            await pending;
            if (fail) throw new Error("Destination unavailable");
          },
          component: () => <h1>Page B</h1>,
          errorComponent: () => <h1>Destination unavailable</h1>
        })
      ]
    });
    const unload = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    try {
      expect(unload()).toBe(true);
      await click("Push");
      await waitFor(() => expect(blocked()).toBe("Blocked"));
      await click("Leave");
      await waitFor(() => expect(router.state.isLoading).toBe(true));
      // The user's decision also covers a deployment recovery while loading B.
      expect(unload()).toBe(false);
      release();
      await screen.findByRole("heading", { name: fail ? "Destination unavailable" : "Page B" });
      // This fixture keeps its editor mounted across routes: later work is protected.
      await waitFor(() => expect(unload()).toBe(true));
    } finally {
      release();
      unmount();
      history.destroy();
    }
  }
);

it.each(["Stay", "Leave"])(
  "keeps the latest decision reachable after two native Back presses: %s",
  async (decision) => {
    window.history.replaceState(null, "", "/a");
    const history = createBrowserHistory();
    const { router, unmount } = await renderWithRouter(<Editor initialDirty={false} />, {
      history,
      routes
    });
    try {
      await click("Push");
      await waitFor(() => expect(router.state.location.pathname).toBe("/b"));
      await act(() => router.navigate({ href: "/a?later=true" }));
      await click("Toggle dirty");
      await act(async () => router.history.back());
      await waitFor(() => expect(blocked()).toBe("Blocked"));
      await act(async () => router.history.back());
      await waitFor(() => expect(window.location.pathname + window.location.search).toBe("/a"));
      expect(blocked()).toBe("Blocked");
      await click(decision);
      const destination = decision === "Stay" ? "/a?later=true" : "/a";
      await waitFor(() => expect(router.state.location.href).toBe(destination));
      await waitFor(() =>
        expect(window.location.pathname + window.location.search).toBe(destination)
      );
      await act(async () =>
        decision === "Stay" ? router.history.back() : router.history.forward()
      );
      await waitFor(() => expect(blocked()).toBe("Blocked"));
      await click("Leave");
      await waitFor(() => expect(router.state.location.pathname).toBe("/b"));
      expect(window.location.pathname).toBe("/b");
    } finally {
      unmount();
      history.destroy();
    }
  }
);
