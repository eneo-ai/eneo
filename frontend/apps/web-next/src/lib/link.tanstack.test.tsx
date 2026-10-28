// @vitest-environment jsdom
import { Link as AstryxLink } from "@astryxdesign/core/Link";
import { createRoute, type AnyRootRoute } from "@tanstack/react-router";
import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderWithRouter } from "@/test/router";
import { Link } from "./link.tanstack";

// The app's LinkProvider (AstryxProvider) renders @/lib/link: here, this one.
vi.mock("@/lib/link", () => import("@/lib/link.tanstack"));

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const page = (path: string) => (root: AnyRootRoute) =>
  createRoute({ getParentRoute: () => root, path, component: () => null });

const current = () => document.querySelectorAll("[aria-current=page]");

it("marks one link current: the one whose path and query match", async () => {
  await renderWithRouter(
    <nav>
      <Link href="/spaces/personal/chat">Ny konversation</Link>
      <Link href="/spaces/personal/chat?session_id=x">Konversationen</Link>
    </nav>,
    { route: "/spaces/personal/chat?session_id=x" }
  );

  expect(current()).toHaveLength(1);
  expect(screen.getByRole("link", { name: "Konversationen" }).getAttribute("aria-current")).toBe(
    "page"
  );
});

it("does not mark a section current on a page below it", async () => {
  await renderWithRouter(
    <nav>
      <Link href="/admin">Admin</Link>
      <Link href="/admin/users">Användare</Link>
    </nav>,
    { route: "/admin/users" }
  );

  expect(screen.getByRole("link", { name: "Admin" }).hasAttribute("aria-current")).toBe(false);
  expect(current()).toHaveLength(1);
});

it("lets the caller's aria-current win, even undefined", async () => {
  await renderWithRouter(
    <Link href="/admin/users" aria-current={undefined}>
      Användare
    </Link>,
    { route: "/admin/users" }
  );

  expect(current()).toHaveLength(0);
});

it("navigates in the app, without a document load", async () => {
  const { router } = await renderWithRouter(<Link href="/a?tab=x#top">A</Link>, {
    routes: (root) => [page("/a")(root)]
  });

  const link = screen.getByRole("link", { name: "A" });
  expect(link.getAttribute("href")).toBe("/a?tab=x#top");
  await act(async () => fireEvent.click(link));

  expect(router.state.location.href).toBe("/a?tab=x#top");
});

it("loads the target ahead on hover, unless prefetch is false", async () => {
  const { router } = await renderWithRouter(
    <>
      <Link href="/a">Förladdas</Link>
      <Link href="/b" prefetch={false}>
        Förladdas inte
      </Link>
    </>,
    { routes: (root) => [page("/a")(root), page("/b")(root)] }
  );
  const preload = vi.spyOn(router, "preloadRoute");
  vi.useFakeTimers();

  fireEvent.mouseEnter(screen.getByRole("link", { name: "Förladdas inte" }));
  fireEvent.mouseEnter(screen.getByRole("link", { name: "Förladdas" }));
  await act(() => vi.advanceTimersByTimeAsync(100));

  expect(preload).toHaveBeenCalledTimes(1);
  expect(preload).toHaveBeenCalledWith(expect.objectContaining({ to: "/a" }));
});

it("does not scroll to a hash target when scroll is false", async () => {
  await renderWithRouter(
    <>
      <Link href="/a#target" scroll={false}>
        Utan scroll
      </Link>
      <p id="target">Mål</p>
    </>,
    { routes: (root) => [page("/a")(root)] }
  );
  const target = screen.getByText("Mål");
  target.scrollIntoView = vi.fn();

  await act(async () => fireEvent.click(screen.getByRole("link", { name: "Utan scroll" })));

  expect(target.scrollIntoView).not.toHaveBeenCalled();
});

it("leaves a download to the browser", async () => {
  const { router } = await renderWithRouter(
    <Link href="/a?download=1" download="report.csv">
      Ladda ner
    </Link>,
    { routes: (root) => [page("/a")(root)] }
  );
  const navigate = vi.spyOn(router, "navigate");
  let prevented: boolean | undefined;
  // jsdom cannot download; record and stop the browser's action after the app's handlers ran.
  const stop = (event: Event) => {
    prevented = event.defaultPrevented;
    event.preventDefault();
  };
  document.addEventListener("click", stop);

  fireEvent.click(screen.getByRole("link", { name: "Ladda ner" }));

  document.removeEventListener("click", stop);
  expect(prevented).toBe(false);
  expect(navigate).not.toHaveBeenCalled();
});

it("leaves another site to the browser", async () => {
  const { router } = await renderWithRouter(
    <>
      <Link href="https://example.org/x">Extern</Link>
      <Link href="//example.org/y">Utan schema</Link>
    </>
  );
  const navigate = vi.spyOn(router, "navigate");
  // jsdom cannot load another document; stop it after the app's handlers ran.
  const stop = (event: Event) => event.preventDefault();
  document.addEventListener("click", stop);

  for (const [name, href] of [
    ["Extern", "https://example.org/x"],
    ["Utan schema", "//example.org/y"]
  ]) {
    const link = screen.getByRole("link", { name });
    expect(link.getAttribute("href")).toBe(href);
    fireEvent.click(link);
  }

  document.removeEventListener("click", stop);
  expect(navigate).not.toHaveBeenCalled();
});

it("renders an Astryx link through it, without Astryx's router prop `to`", async () => {
  const { router } = await renderWithRouter(<AstryxLink href="/spaces/list">Ytor</AstryxLink>);

  const link = screen.getByRole("link", { name: "Ytor" });
  expect(link.getAttribute("href")).toBe("/spaces/list");
  expect(link.hasAttribute("to")).toBe(false);
  await act(async () => fireEvent.click(link));
  expect(router.state.location.pathname).toBe("/spaces/list");
});
