// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import type { Permission } from "@/lib/auth/permissions";
import { expectNoAxeViolations } from "@/test/axe";
import { router, setRoute } from "@/test/navigation";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import ShellCommandPalette from "./command-palette";
import { recentConversationsQueryOptions } from "./nav-data";

vi.mock("next/navigation", () => import("@/test/navigation"));

function seededClient() {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["dashboard"], {
    spaces: {
      items: [
        {
          id: "p",
          name: "Personal",
          personal: true,
          organization: false,
          default_assistant: { id: "default-assistant" },
          applications: { assistants: { items: [] }, apps: { items: [] } }
        },
        {
          id: "s1",
          name: "Upphandling",
          personal: false,
          organization: false,
          applications: {
            assistants: { items: [{ id: "a1", name: "Upphandlingsassistenten" }] },
            apps: { items: [] }
          }
        }
      ]
    }
  });
  queryClient.setQueryData(
    ["spaces"],
    [{ id: "s1", name: "Upphandling", description: null, personal: false, organization: false }]
  );
  queryClient.setQueryData(
    recentConversationsQueryOptions(browserApi, "default-assistant", 20).queryKey,
    [{ id: "c1", name: "Upphandlingsanalys mot LOU" }]
  );
  queryClient.setQueryData(["spaces", "s1"], {
    id: "s1",
    name: "Upphandling",
    personal: false,
    knowledge: {
      groups: { items: [{ id: "col1", name: "Upphandlingspolicy" }] },
      websites: { items: [] }
    }
  });
  return queryClient;
}

function renderPalette(permissions: Permission[] = []) {
  const onCreateSpace = vi.fn();
  const onOpenChange = vi.fn();
  renderInApp(
    <ShellCommandPalette isOpen onOpenChange={onOpenChange} onCreateSpace={onCreateSpace} />,
    { queryClient: seededClient(), appContext: testAppContext({ permissions }) }
  );
  return { onCreateSpace, onOpenChange };
}

function search(query: string) {
  fireEvent.change(screen.getByRole("combobox"), { target: { value: query } });
}

beforeEach(() => setRoute("/spaces/s1/knowledge"));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const ok = (data: unknown) =>
  Promise.resolve({ data, error: undefined, response: new Response("{}", { status: 200 }) });

describe("ShellCommandPalette", () => {
  it("is a named dialog with a labelled combobox and grouped results", async () => {
    renderPalette();
    const dialog = screen.getByRole("dialog", { name: "Sök i Eneo" });
    const combobox = within(dialog).getByRole("combobox", {
      name: "Sök bland assistenter, ytor, konversationer, kunskap och åtgärder"
    });
    expect(combobox.getAttribute("aria-controls")).toBe(
      within(dialog).getByRole("listbox").getAttribute("id")
    );

    await within(dialog).findByRole("option", { name: /Upphandlingsassistenten/ });
    for (const group of ["Assistenter", "Ytor", "Konversationer", "Åtgärder"]) {
      expect(within(dialog).getByRole("group", { name: group })).toBeTruthy();
    }
    // Knowledge and admin pages wait for a query.
    expect(within(dialog).queryByRole("group", { name: "Kunskap" })).toBeNull();
    await expectNoAxeViolations(document.body);
  });

  it("searches everything and highlights the match", async () => {
    renderPalette();
    await screen.findByRole("option", { name: /Upphandlingsassistenten/ });
    search("policy");

    // jsdom's name computation puts a space around the highlighted <strong>.
    const option = await screen.findByRole("option", { name: /Upphandlings ?policy/ });
    expect(within(option).getByText("policy", { selector: "strong" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Kunskap" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Upphandlingsassistenten/ })).toBeNull();
  });

  it("opens the chosen result", async () => {
    renderPalette();
    fireEvent.click(await screen.findByRole("option", { name: /Upphandlingsanalys mot LOU/ }));
    expect(router.push).toHaveBeenCalledWith("/spaces/personal/chat?session_id=c1");
  });

  it("opens the highlighted result with Enter", async () => {
    renderPalette();
    await screen.findByRole("option", { name: /Upphandlingsassistenten/ });
    search("upphandlingsassistenten");
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(1));
    const combobox = screen.getByRole("combobox");
    fireEvent.keyDown(combobox, { key: "ArrowDown" });
    fireEvent.keyDown(combobox, { key: "Enter" });
    expect(router.push).toHaveBeenCalledWith("/dashboard/a1?tab=chat");
  });

  it("offers Skapa yta and admin pages to those allowed", async () => {
    const { onCreateSpace } = renderPalette(["admin", "shared_spaces"]);
    await screen.findByRole("option", { name: /Upphandlingsassistenten/ });

    search("modell");
    expect(
      await screen.findByRole("option", { name: /^Administration › Modell ?er$/ })
    ).toBeTruthy();

    search("skapa");
    fireEvent.click(await screen.findByRole("option", { name: /^Skapa ?yta$/ }));
    await waitFor(() => expect(onCreateSpace).toHaveBeenCalledTimes(1));
  });

  it("fetches what the cache holds as stale or invalidated before listing it", async () => {
    setRoute("/dashboard");
    // The app's 30 s staleTime: the dashboard below is older than that.
    const queryClient = testQueryClient();
    const dashboard = (assistant: string) => ({
      spaces: {
        items: [
          {
            id: "p",
            name: "Personal",
            personal: true,
            organization: false,
            default_assistant: { id: "default-assistant" },
            applications: { assistants: { items: [] }, apps: { items: [] } }
          },
          {
            id: "s1",
            name: "Upphandling",
            personal: false,
            organization: false,
            applications: {
              assistants: { items: [{ id: "a1", name: assistant }] },
              apps: { items: [] }
            }
          }
        ]
      }
    });
    // Older than the stale time: an assistant was renamed since.
    queryClient.setQueryData(["dashboard"], dashboard("Gammalt namn"), {
      updatedAt: Date.now() - 60_000
    });
    queryClient.setQueryData(["spaces"], []);
    // Fresh, but the chat invalidated it: a conversation was deleted.
    const conversationsKey = recentConversationsQueryOptions(
      browserApi,
      "default-assistant",
      20
    ).queryKey;
    queryClient.setQueryData(conversationsKey, [{ id: "c1", name: "Raderad konversation" }]);
    await queryClient.invalidateQueries({
      queryKey: ["conversations", "assistant", "default-assistant"]
    });
    const get = vi.spyOn(browserApi, "GET").mockImplementation(((path: string) => {
      if (path === "/api/v1/dashboard/") return ok(dashboard("Nytt namn"));
      if (path === "/api/v1/conversations/") return ok({ items: [{ id: "c2", name: "Ny fråga" }] });
      return ok({});
    }) as unknown as typeof browserApi.GET);

    renderInApp(<ShellCommandPalette isOpen onOpenChange={vi.fn()} onCreateSpace={vi.fn()} />, {
      queryClient
    });

    expect(await screen.findByRole("option", { name: /Nytt namn/ })).toBeTruthy();
    expect(screen.getByRole("option", { name: /Ny fråga/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Gammalt namn|Raderad konversation/ })).toBeNull();
    // The fresh spaces list came from the cache.
    expect(get).not.toHaveBeenCalledWith("/api/v1/spaces/", expect.anything());
  });

  it("hides Skapa yta and admin pages from others", async () => {
    renderPalette();
    await screen.findByRole("option", { name: /Upphandlingsassistenten/ });
    search("skapa");
    await screen.findByText("Inga resultat hittades");
    search("modell");
    await waitFor(() => expect(screen.queryByRole("option")).toBeNull());
  });
});
