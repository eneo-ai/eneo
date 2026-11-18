// @vitest-environment jsdom
import { createRoute, HeadContent, type AnyRootRoute } from "@tanstack/react-router";
import { act, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderWithRouter } from "@/test/router";
import { RouteAnnouncer } from "./route-announcer";

const announce = vi.hoisted(() => vi.fn());
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => announce
}));

beforeEach(() => announce.mockClear());

const page = (root: AnyRootRoute, path: string, title: string) =>
  createRoute({
    getParentRoute: () => root,
    path,
    head: () => ({ meta: [{ title }] }),
    component: () => <h1>{title}</h1>
  });

async function renderAt(route: string) {
  const { router } = await renderWithRouter(
    <>
      <HeadContent />
      <RouteAnnouncer />
    </>,
    { route, routes: (root) => [page(root, "/a", "A · Eneo"), page(root, "/b", "B · Eneo")] }
  );
  return router;
}

/** Lets the frame after a render run, where an announcement would be made. */
const nextFrame = () => act(() => new Promise((resolve) => requestAnimationFrame(resolve)));

it("announces nothing on the first page load", async () => {
  await renderAt("/a");
  await nextFrame();

  expect(document.title).toBe("A · Eneo");
  expect(announce).not.toHaveBeenCalled();
});

it("announces the new page's title once, without moving focus", async () => {
  const router = await renderAt("/a");

  await act(() => router.navigate({ href: "/b" }));

  await waitFor(() => expect(announce).toHaveBeenCalledWith("B · Eneo"));
  await nextFrame();
  expect(announce).toHaveBeenCalledTimes(1);
  expect(document.activeElement).toBe(document.body);
});

it("announces nothing when only the query changes", async () => {
  const router = await renderAt("/a");

  await act(() => router.navigate({ href: "/a?x=1" }));
  await nextFrame();

  expect(router.state.location.href).toBe("/a?x=1");
  expect(announce).not.toHaveBeenCalled();
});
