// @vitest-environment jsdom
import { createRoute, HeadContent, Outlet } from "@tanstack/react-router";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { renderWithRouter } from "@/test/router";
import { testAppContext, testQueryClient } from "@/test/render";
import { sessionKeys } from "./api/session";
import { resourceTitle, spaceTitle } from "./route-head";
import { requirePermission } from "./route-helpers";

afterEach(() => vi.useRealTimers());

it("uses the deepest title and falls back to its page name with the parent space", async () => {
  const { router } = await renderWithRouter(<HeadContent />, {
    route: "/spaces/personal/assistants/a",
    routes: (root) => {
      const app = createRoute({ getParentRoute: () => root, id: "_app", component: Outlet });
      const space = createRoute({
        getParentRoute: () => app,
        path: "spaces/$spaceId",
        loader: () => ({ name: "Backend name", personal: true, organization: false }),
        head: ({ matches, match }) => spaceTitle(matches, match.context.t),
        component: Outlet
      });
      const resource = createRoute({
        getParentRoute: () => space,
        path: "assistants/$assistantId",
        loader: ({ params }) => (params.assistantId === "missing" ? undefined : { name: "Avtal" }),
        head: resourceTitle("assistants"),
        component: () => <h1>Resource</h1>
      });
      return [app.addChildren([space.addChildren([resource])])];
    }
  });
  await waitFor(() => expect(document.title).toBe("Avtal · Personligt · Eneo"));
  await act(() => router.navigate({ href: "/spaces/personal/assistants/missing" }));
  await waitFor(() => expect(document.title).toBe("Assistenter · Personligt · Eneo"));
  expect(document.querySelectorAll("title")).toHaveLength(1);
});

it("performs the permission redirect as internal navigation", async () => {
  const queryClient = testQueryClient();
  queryClient.setQueryData(sessionKeys.me, testAppContext({ permissions: [] }).user);
  const { router } = await renderWithRouter(null, {
    route: "/admin",
    queryClient,
    routes: (root) => [
      createRoute({
        getParentRoute: () => root,
        path: "/admin",
        beforeLoad: () => requirePermission({ queryClient }, "admin", "/public"),
        component: () => <h1>Administration</h1>
      }),
      createRoute({ getParentRoute: () => root, path: "/public", component: () => <h1>Public</h1> })
    ]
  });
  expect(await screen.findByRole("heading", { name: "Public" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/public");
  expect(screen.queryByRole("heading", { name: "Administration" })).toBeNull();
});

it("keeps a draft for search changes and flushes it only to its original entity on ID changes", async () => {
  const save = vi.fn(async (_id: string, _value: string) => {});
  const { router } = await renderWithRouter(null, {
    route: "/assistants/a",
    routes: (root) => {
      const editor = createRoute({
        getParentRoute: () => root,
        path: "/assistants/$assistantId",
        remountDeps: ({ params }) => params.assistantId,
        component: Editor
      });
      function Editor() {
        const { assistantId } = editor.useParams();
        const field = useAutosaveField({
          key: "prompt",
          value: `Saved ${assistantId}`,
          save: (value) => save(assistantId, value),
          commitDebounceMs: 1000
        });
        return (
          <input
            aria-label="Prompt"
            value={field.value}
            onChange={(event) => field.setValue(event.target.value)}
          />
        );
      }
      return [editor];
    }
  });
  const input = await screen.findByRole("textbox", { name: "Prompt" });
  vi.useFakeTimers();
  fireEvent.change(input, { target: { value: "Draft A" } });
  await act(() => router.navigate({ href: "/assistants/a?tab=advanced" }));
  expect(screen.getByRole("textbox", { name: "Prompt" })).toBe(input);
  expect(save).not.toHaveBeenCalled();
  await act(() => router.navigate({ href: "/assistants/b" }));
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(save).toHaveBeenCalledExactlyOnceWith("a", "Draft A");
  expect(screen.getByRole<HTMLInputElement>("textbox", { name: "Prompt" }).value).toBe("Saved b");
});
