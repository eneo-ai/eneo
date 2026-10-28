// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { router, setRoute } from "@/test/navigation";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const model = {
  model_id: "model-1",
  model_name: "gpt-5",
  model_nickname: "GPT-5",
  model_org: "OpenAI",
  model_provider: "Azure",
  input_token_usage: 1200,
  output_token_usage: 300,
  total_token_usage: 1500,
  request_count: 4
};

type Query = Record<string, string | number | undefined>;

const apiState = vi.hoisted(() => ({
  failingPaths: new Set<string>(),
  /** Token usage periods (start dates) that fail. */
  failingStarts: new Set<string>(),
  calls: [] as { path: string; query: Query }[],
  models: [] as (typeof model)[],
  spaces: 2
}));

/** 30 users: the first uses a lot, the second some, the rest little. */
function usersPage(query: Query) {
  const all = Array.from({ length: 30 }, (_, index) => ({
    user_id: `user-${index + 1}`,
    username: index === 0 ? "Anna Lind" : `user${index + 1}`,
    email: index === 0 ? "anna.lind@example.se" : `user${index + 1}`,
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_tokens: index === 0 ? 600_000 : index === 1 ? 60_000 : 1_000,
    total_requests: 4,
    models_used: []
  }));
  const search = typeof query.search === "string" ? query.search : "";
  const matching = all.filter((user) => user.username.includes(search));
  const page = Number(query.page);
  const perPage = Number(query.per_page);
  const users = matching.slice((page - 1) * perPage, page * perPage);
  return {
    total_users: matching.length,
    total_tokens: users.reduce((sum, user) => sum + user.total_tokens, 0),
    total_requests: 0,
    users
  };
}

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string, init?: { params?: { query?: Query } }) => {
      const query = init?.params?.query ?? {};
      apiState.calls.push({ path, query });
      if (apiState.failingPaths.has(path) || apiState.failingStarts.has(String(query.start_date))) {
        return Promise.resolve({
          error: {
            error: "Internal server error",
            error_id: "8bc91e0a",
            message:
              "An unexpected error occurred. Please try again or contact support with the error_id."
          },
          response: new Response("{}", { status: 500, headers: { "x-trace-id": "trace-123" } })
        });
      }
      const data =
        path === "/api/v1/token-usage/"
          ? {
              total_token_usage: 1500,
              total_input_token_usage: 1200,
              total_output_token_usage: 300,
              models: apiState.models
            }
          : path === "/api/v1/token-usage/users"
            ? usersPage(query)
            : path === "/api/v1/storage/"
              ? { total_used: 600, personal_used: 200, shared_used: 400, limit: 1000 }
              : path === "/api/v1/storage/spaces/"
                ? {
                    items: Array.from({ length: apiState.spaces }, (_, index) => ({
                      id: `space-${index + 1}`,
                      name: "Upphandling",
                      size: 100 * (index + 1),
                      members:
                        index === 0 ? [{ id: "m1", email: "a@example.se", role: "admin" }] : []
                    }))
                  }
                : path === "/api/v1/ai-models/"
                  ? {
                      completion_models: [
                        {
                          id: "model-1",
                          input_cost_per_token: "0.001",
                          output_cost_per_token: "0.002"
                        }
                      ],
                      embedding_models: [],
                      transcription_models: []
                    }
                  : {};
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { UsagePage } from "./usage-page";

function resetApi() {
  apiState.failingPaths.clear();
  apiState.failingStarts.clear();
  apiState.calls.length = 0;
  apiState.models = [
    model,
    { ...model, model_id: "model-2", model_nickname: "GPT-5 (annan konfiguration)" }
  ];
  apiState.spaces = 2;
}
resetApi();

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  resetApi();
});

function usersCalls() {
  return apiState.calls.filter((call) => call.path === "/api/v1/token-usage/users");
}

/**
 * The error banner. Astryx's announcer keeps an empty `alert` region in the
 * document once a test announced something, so find the banner by its text.
 */
async function findError() {
  const message = await screen.findByText("Vi upplever vissa svårigheter, försök igen senare.");
  return message.closest<HTMLElement>('[role="alert"]')!;
}

async function openUsers(route = "/admin/usage") {
  const view = renderInApp(<UsagePage />, { route });
  // Radix tabs switch on mouse down.
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Användare" }));
  return { ...view, table: await screen.findByRole("table", { name: "Användning per användare" }) };
}

describe("UsagePage", () => {
  it("keeps same-named models distinct and names each tab's table", async () => {
    const consoleError = vi.spyOn(console, "error");
    const { container } = renderInApp(<UsagePage />, { route: "/admin/usage" });

    const tokens = await screen.findByRole("table", { name: "Användning per modell" });
    expect(within(tokens).getByText("GPT-5")).toBeTruthy();
    expect(within(tokens).getByText("GPT-5 (annan konfiguration)")).toBeTruthy();
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("same key");
    await expectNoAxeViolations(container);

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Användare" }));
    const users = await screen.findByRole("table", { name: "Användning per användare" });
    expect(within(users).getByRole("link", { name: /Anna Lind/ })).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Lagring" }));
    const storage = await screen.findByRole("table", { name: "Offentliga ytor" });
    expect(within(storage).getAllByText("Upphandling")).toHaveLength(2);
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("same key");
  });

  it("shows the providers and an estimated cost per model, sortable and ten at a time", async () => {
    apiState.models = Array.from({ length: 12 }, (_, index) => ({
      ...model,
      model_id: `model-${index + 1}`,
      model_nickname: `Modell ${index + 1}`,
      model_provider: index === 0 ? "Azure" : "Mistral",
      total_token_usage: 1500
    }));
    const { container } = renderInApp(<UsagePage />, { route: "/admin/usage" });

    const table = await screen.findByRole("table", { name: "Användning per modell" });
    expect(screen.getByText("Azure")).toBeTruthy();
    expect(screen.getByText("Mistral")).toBeTruthy();
    expect(within(table).getAllByRole("row")).toHaveLength(11);
    // 1200 × 0.001 + 300 × 0.002 for the one model with a rate.
    expect(within(table).getByText("$1.80")).toBeTruthy();

    fireEvent.click(within(table).getByRole("button", { name: /Beräknad kostnad/ }));
    fireEvent.click(within(table).getByRole("button", { name: /Beräknad kostnad/ }));
    const firstRow = within(table).getAllByRole("row")[1]!;
    expect(within(firstRow).getByText("$1.80")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Visa alla 12 modeller" }));
    expect(within(table).getAllByRole("row")).toHaveLength(13);
    fireEvent.click(screen.getByRole("button", { name: "Visa endast 10 modeller" }));
    expect(within(table).getAllByRole("row")).toHaveLength(11);
    await expectNoAxeViolations(container);
  });

  it("refetches the model table for a new date range and keeps it for the users tab", async () => {
    renderInApp(<UsagePage />, { route: "/admin/usage" });
    await screen.findByRole("table", { name: "Användning per modell" });
    expect(apiState.calls.filter((call) => call.path === "/api/v1/token-usage/")).toHaveLength(1);

    fireEvent.change(screen.getByLabelText("Från"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("till"), { target: { value: "2026-09-16" } });
    await waitFor(() =>
      expect(apiState.calls.at(-1)).toEqual({
        path: "/api/v1/token-usage/",
        query: { start_date: "2026-09-01", end_date: "2026-09-17" }
      })
    );
    expect(window.location.search).toBe("?from=2026-09-01&to=2026-09-16");
    // The overview stays on the last 30 days.
    expect(screen.getByText(/Senaste 30 dagarna/)).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Användare" }));
    await screen.findByRole("table", { name: "Användning per användare" });
    expect(usersCalls().at(-1)?.query.start_date).toBe("2026-09-01");
    // 15 days halve the thresholds of 30.
    expect(screen.getByText(/Användare med hög användning \(>250/)).toBeTruthy();
  });

  it("keeps the date range usable when a period fails, and the overview on screen", async () => {
    apiState.failingStarts.add("2026-09-01");
    renderInApp(<UsagePage />, { route: "/admin/usage" });
    await screen.findByRole("table", { name: "Användning per modell" });

    fireEvent.change(screen.getByLabelText("Från"), { target: { value: "2026-09-01" } });
    expect(await findError()).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Token-sammanfattning/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Återställ" }));
    expect(await screen.findByRole("table", { name: "Användning per modell" })).toBeTruthy();
    expect(screen.queryByText("Vi upplever vissa svårigheter, försök igen senare.")).toBeNull();
  });

  it("says when the ratecard failed instead of showing every cost as unknown", async () => {
    apiState.failingPaths.add("/api/v1/ai-models/");
    renderInApp(<UsagePage />, { route: "/admin/usage" });

    const table = await screen.findByRole("table", { name: "Användning per modell" });
    const retry = await screen.findByRole("button", {
      name: "Försök igen: Beräknade kostnader kunde inte hämtas"
    });
    expect(within(table).queryByText("$1.80")).toBeNull();

    apiState.failingPaths.delete("/api/v1/ai-models/");
    fireEvent.click(retry);
    expect(await within(table).findByText("$1.80")).toBeTruthy();
    expect(screen.queryByText("Beräknade kostnader kunde inte hämtas")).toBeNull();
  });

  it("follows a navigation to another view of the page while it is open", async () => {
    const { rerender } = renderInApp(<UsagePage />, {
      route: "/admin/usage?tab=users&userSearch=user1"
    });
    const search = await screen.findByRole("textbox", { name: /Sök användarnamn/ });
    expect(search).toHaveProperty("value", "user1");

    // The App Router rerenders the page on a navigation within it.
    act(() => setRoute("/admin/usage?tab=users&userSearch=user2"));
    rerender(<UsagePage />);
    expect(screen.getByRole("textbox", { name: /Sök användarnamn/ })).toHaveProperty(
      "value",
      "user2"
    );
    await waitFor(() => expect(usersCalls().at(-1)?.query.search).toBe("user2"));

    act(() => setRoute("/admin/usage"));
    rerender(<UsagePage />);
    expect(await screen.findByRole("table", { name: "Användning per modell" })).toBeTruthy();
  });

  it("pages, searches and sorts users on the server and keeps it all in the URL", async () => {
    const { container, table } = await openUsers();

    expect(usersCalls()[0]?.query).toMatchObject({
      page: 1,
      per_page: 25,
      sort_by: "total_tokens",
      sort_order: "desc",
      search: undefined
    });
    expect(screen.getByText("1–25 av 30")).toBeTruthy();
    expect(within(table).getAllByRole("row")).toHaveLength(26);
    const anna = within(table)
      .getByRole("link", { name: /Anna Lind/ })
      .closest("tr")!;
    expect(within(anna).getByText("anna.lind@example.se")).toBeTruthy();
    expect(within(anna).getByText("Hög")).toBeTruthy();
    expect(screen.getByText(/Användare med hög användning \(>500/)).toBeTruthy();
    expect(screen.getByText(/Användare med medelhög användning/)).toBeTruthy();
    expect(screen.getByText(/Användare med låg användning/)).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: "Gå till sista sidan" }));
    expect(await screen.findByText("26–30 av 30")).toBeTruthy();
    expect(usersCalls().at(-1)?.query.page).toBe(2);
    expect(window.location.search).toBe("?tab=users&page=2");

    // A new sort starts over on the first page; names sort A–Z first.
    fireEvent.click(screen.getByRole("button", { name: /^Sortera efter Användare/ }));
    await waitFor(() =>
      expect(usersCalls().at(-1)?.query).toMatchObject({
        page: 1,
        sort_by: "username",
        sort_order: "asc"
      })
    );
    const header = screen.getByRole("columnheader", { name: /Användare/ });
    expect(header.getAttribute("aria-sort")).toBe("ascending");

    // A second click on the active column flips it, and a figure column can
    // reach ascending order.
    fireEvent.click(screen.getByRole("button", { name: /^Sortera efter Användare/ }));
    await waitFor(() =>
      expect(usersCalls().at(-1)?.query).toMatchObject({ sort_by: "username", sort_order: "desc" })
    );
    fireEvent.click(screen.getByRole("button", { name: /^Sortera efter Förfrågningar/ }));
    await waitFor(() =>
      expect(usersCalls().at(-1)?.query).toMatchObject({ sort_by: "requests", sort_order: "desc" })
    );
    fireEvent.click(screen.getByRole("button", { name: /^Sortera efter Förfrågningar/ }));
    await waitFor(() =>
      expect(usersCalls().at(-1)?.query).toMatchObject({ sort_by: "requests", sort_order: "asc" })
    );
    // Back to names: served from the cache, so check the view, not a request.
    fireEvent.click(screen.getByRole("button", { name: /^Sortera efter Användare/ }));
    await waitFor(() =>
      expect(
        screen.getByRole("columnheader", { name: /Användare/ }).getAttribute("aria-sort")
      ).toBe("ascending")
    );

    fireEvent.change(screen.getByRole("textbox", { name: /Sök användarnamn/ }), {
      target: { value: "  user1  " }
    });
    fireEvent.click(screen.getByRole("button", { name: "Sök" }));
    expect(await screen.findByText("1–10 av 10")).toBeTruthy();
    expect(usersCalls().at(-1)?.query).toMatchObject({ page: 1, search: "user1" });
    expect(window.location.search).toBe(
      "?tab=users&sortBy=username&sortOrder=asc&userSearch=user1"
    );

    // The user's page carries the view so its back link returns to it.
    expect(
      within(screen.getByRole("table", { name: "Användning per användare" }))
        .getAllByRole("link")[0]!
        .getAttribute("href")
    ).toMatch(
      /^\/admin\/usage\/users\/user-\d+\?tab=users&sortBy=username&sortOrder=asc&userSearch=user1$/
    );

    fireEvent.click(screen.getByRole("button", { name: "Rensa filter" }));
    expect(await screen.findByText("1–25 av 30")).toBeTruthy();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("opens the tab, page, sort and search a URL asks for", async () => {
    renderInApp(<UsagePage />, {
      route: "/admin/usage?tab=users&page=2&sortBy=requests&sortOrder=asc&userSearch=user"
    });

    expect(await screen.findByRole("table", { name: "Användning per användare" })).toBeTruthy();
    expect(usersCalls()[0]?.query).toMatchObject({
      page: 2,
      sort_by: "requests",
      sort_order: "asc",
      search: "user"
    });
    expect(screen.getByRole("textbox", { name: /Sök användarnamn/ })).toHaveProperty(
      "value",
      "user"
    );
  });

  it("shows a page past the end as the last page", async () => {
    renderInApp(<UsagePage />, { route: "/admin/usage?tab=users&page=9" });

    expect(await screen.findByText("26–30 av 30")).toBeTruthy();
    expect(usersCalls().at(-1)?.query.page).toBe(2);
  });

  it("shows the storage limit, free space, shares and members per space", async () => {
    apiState.spaces = 11;
    const { container } = renderInApp(<UsagePage />, { route: "/admin/usage?tab=storage" });

    const table = await screen.findByRole("table", { name: "Offentliga ytor" });
    expect(screen.getByText("Tillgänglig").closest("p")?.textContent).toMatch(/1\s000/);
    const legend = (name: string) =>
      screen.getAllByRole("listitem").find((item) => item.textContent?.startsWith(name))
        ?.textContent;
    expect(legend("Offentliga ytor")).toMatch(/400\sB \(40\s%\)/);
    expect(legend("Personliga ytor")).toMatch(/200\sB \(20\s%\)/);
    expect(legend("Ledigt")).toMatch(/400\sB \(40\s%\)/);
    // The largest ten spaces first; the smallest, with a member, behind "show all".
    expect(within(table).getAllByRole("row")).toHaveLength(11);
    expect(within(table).queryByLabelText("1 medlem")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Visa alla 11 ytor" }));
    expect(within(table).getAllByRole("row")).toHaveLength(12);
    expect(within(table).getByLabelText("1 medlem")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("keeps the other tabs usable when token usage fails and retries that tab", async () => {
    apiState.failingPaths.add("/api/v1/token-usage/");
    const { container } = renderInApp(<UsagePage />, { route: "/admin/usage" });

    const alert = await findError();
    fireEvent.click(within(alert).getByRole("button", { name: "Expandera" }));
    expect(screen.getByText("Fel-ID: 8bc91e0a")).toBeTruthy();
    expect(screen.getByText("Spårnings-ID: trace-123")).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Lagring" }));
    expect(await screen.findByRole("table", { name: "Offentliga ytor" })).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Tokens" }));
    // Back on the tab the failed read retries on mount; its retry button stays, busy.
    const retry = await screen.findByRole("button", { name: "Försök igen" });
    await waitFor(() => expect(retry.getAttribute("aria-busy")).not.toBe("true"));
    apiState.failingPaths.delete("/api/v1/token-usage/");
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByRole("table", { name: "Användning per modell" })).toBeTruthy();
  });

  it("retries a failed storage request without losing tokens", async () => {
    apiState.failingPaths.add("/api/v1/storage/spaces/");
    renderInApp(<UsagePage />, { route: "/admin/usage" });

    expect(await screen.findByRole("table", { name: "Användning per modell" })).toBeTruthy();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Lagring" }));
    expect(await findError()).toBeTruthy();

    apiState.failingPaths.delete("/api/v1/storage/spaces/");
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByRole("table", { name: "Offentliga ytor" })).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Tokens" }));
    expect(await screen.findByRole("table", { name: "Användning per modell" })).toBeTruthy();
  });

  it("shows and retries an error on the users tab", async () => {
    apiState.failingPaths.add("/api/v1/token-usage/users");
    renderInApp(<UsagePage />, { route: "/admin/usage" });

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Användare" }));
    expect(await findError()).toBeTruthy();

    apiState.failingPaths.delete("/api/v1/token-usage/users");
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByRole("table", { name: "Användning per användare" })).toBeTruthy();
  });
});
