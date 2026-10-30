// @vitest-environment jsdom
import { createBrowserHistory, createRoute, type AnyRootRoute } from "@tanstack/react-router";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { renderWithRouter } from "@/test/router";
import Link from "./link.tanstack";
import { pushUrl, useLeaveConfirmation, useRouter } from "./navigation.tanstack";

vi.mock("@/lib/navigation", () => import("@/lib/navigation.tanstack"));
vi.mock("@/lib/link", () => import("@/lib/link.tanstack"));

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
