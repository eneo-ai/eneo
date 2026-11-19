// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IntlProvider } from "use-intl";
import en from "@/lib/i18n/messages/en.json";
import { replaceUrl } from "@/test/navigation";
import { renderInApp, testAppContext } from "@/test/render";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const counts = (user: number, widget: number, api_key: number) => ({
  total: user + widget + api_key,
  user,
  widget,
  api_key
});

const target = (id: string, name: string, overrides: Record<string, unknown> = {}) => ({
  id,
  kind: "assistant",
  name,
  space_id: `space-${id}`,
  space_name: "Bygg och miljö",
  insight_enabled: true,
  conversations: counts(0, 0, 0),
  questions: 0,
  previous: null,
  ratings: { positive: 0, negative: 0 },
  ...overrides
});

/** Every personal space's assistants together: the same whatever the filters. */
const PERSONAL = { assistants: 3, conversations: counts(40, 0, 2), questions: 90 };

/** Three targets of note, then enough unused assistants for a second page. */
const TARGETS = [
  target("t-1", "Bygglovsassistenten", {
    conversations: counts(742, 468, 74),
    questions: 2946,
    ratings: { positive: 165, negative: 47 }
  }),
  target("t-2", "Upphandlingsstöd", {
    kind: "group_chat",
    space_name: "Ekonomi",
    conversations: counts(611, 0, 0),
    questions: 900
  }),
  target("t-3", "Skolskjutsfrågor", {
    insight_enabled: false,
    ratings: null,
    conversations: counts(31, 69, 0),
    questions: 120
  }),
  ...Array.from({ length: 24 }, (_, index) => target(`u-${index}`, `Oanvänd ${index + 1}`))
];

const state = vi.hoisted(() => ({
  calls: [] as { path: string; query?: Record<string, string> }[]
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string, init?: { params?: { query?: Record<string, string> } }) => {
      state.calls.push({ path, query: init?.params?.query });
      const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
      switch (path) {
        case "/api/v1/token-usage/":
          return ok({
            total_token_usage: 1500,
            total_input_token_usage: 1200,
            total_output_token_usage: 300,
            models: []
          });
        case "/api/v1/analysis/targets/activity/":
          return ok({
            timezone: init!.params!.query!.timezone,
            source: null,
            start: "",
            end: "",
            days: []
          });
        case "/api/v1/analysis/targets/": {
          const query = init!.params!.query! as unknown as Record<string, string | number>;
          const offset = Number(query.offset);
          const named = TARGETS.filter(
            (item) => !query.q || item.name.toLowerCase().includes(String(query.q))
          );
          const matching = named.filter(
            (item) => query.activity !== "unused" || item.conversations.total === 0
          );
          const compared = String(query.compare) === "true";
          // The listed targets that match, plus the personal spaces, which no filter narrows.
          const sum = (source: "total" | "user" | "widget" | "api_key") =>
            matching.reduce(
              (total, item) => total + item.conversations[source],
              PERSONAL.conversations[source]
            );
          return ok({
            items: matching.slice(offset, offset + Number(query.limit)),
            total_count: matching.length,
            limit: Number(query.limit),
            offset,
            personal: {
              ...PERSONAL,
              previous: compared ? { conversations: counts(30, 0, 0), questions: 60 } : null
            },
            totals: {
              conversations: {
                total: sum("total"),
                user: sum("user"),
                widget: sum("widget"),
                api_key: sum("api_key")
              },
              questions: matching.reduce(
                (total, item) => total + item.questions,
                PERSONAL.questions
              ),
              previous: compared ? { conversations: counts(1000, 400, 100), questions: 3000 } : null
            },
            // The search narrows the counts; "Oanvända" does not.
            counts: {
              all: named.length,
              unused: named.filter((item) => item.conversations.total === 0).length
            },
            users: { current: 184, previous: compared ? 160 : null }
          });
        }
        default:
          throw new Error(`Unexpected GET ${path}`);
      }
    }
  }
}));

import { InsightsPage } from "./insights-page";

beforeEach(() => {
  state.calls.length = 0;
});
afterEach(cleanup);

/** The query of every request for the table of assistants and group chats. */
const tableCalls = () =>
  state.calls
    .filter(
      (call) => call.path === "/api/v1/analysis/targets/" && String(call.query?.limit) !== "1"
    )
    .map((call) => call.query);
/** The query of every request for the tiles: the list unfiltered, one row long. */
const tileCalls = () =>
  state.calls
    .filter(
      (call) => call.path === "/api/v1/analysis/targets/" && String(call.query?.limit) === "1"
    )
    .map((call) => call.query);

const tiles = () => screen.getByRole("region", { name: "Nyckeltal" });
const tile = (label: string) => within(tiles()).getByText(label).closest("div")!.textContent;
/** The address the page last wrote. */
const lastAddress = () => new URLSearchParams(String(replaceUrl.mock.calls.at(-1)?.[0]));

function renderPage(
  route = "/admin/insights",
  permissions: NonNullable<Parameters<typeof testAppContext>[0]>["permissions"] = ["insights"]
) {
  return renderInApp(<InsightsPage />, {
    appContext: testAppContext({ permissions }),
    route
  });
}

describe("InsightsPage", () => {
  it("shows the organisation's figures, counted as the table counts", async () => {
    renderPage();
    await screen.findByText("Aktiva assistenter");
    // The listed targets and the personal spaces, by source in words that count conversations.
    expect(tile("Konversationer")).toMatch(
      /^Konversationer2\s0371\s424 från användare, 537 via widget och 76 via API$/
    );
    expect(tile("Frågor")).toMatch(/^Frågor4\s0562 frågor per konversation$/);
    expect(tile("Aktiva användare")).toBe(
      "Aktiva användare184Besökare via widget och anrop via API räknas inte som användare"
    );
    // Three of 27 listed targets were used; group chats count, personal assistants not.
    expect(tile("Aktiva assistenter")).toBe(
      "Aktiva assistenter3 av 2724 har inte använts under periodenGruppchattar räknas med, personliga assistenter inte"
    );
    expect(tileCalls()[0]).toMatchObject({ activity: "all", compare: false, offset: 0 });
    expect(tileCalls()[0]!.q).toBeUndefined();
    // The organisation's days, in the browser's time zone.
    expect(
      state.calls.find((call) => call.path.endsWith("/targets/activity/"))!.query
    ).toMatchObject({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
  });

  it("keeps the figures put while the table is searched, filtered and sorted", async () => {
    renderPage();
    const table = await screen.findByRole("table", { name: "Assistenter och gruppchattar" });
    await screen.findByText("Aktiva assistenter");
    const before = tiles().textContent;
    fireEvent.click(within(table).getByRole("button", { name: "Namn" }));
    await waitFor(() => expect(tableCalls().at(-1)).toMatchObject({ sort: "name" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Sök assistent eller gruppchatt" }), {
      target: { value: "bygg" }
    });
    await waitFor(() => expect(tableCalls().at(-1)).toMatchObject({ q: "bygg" }));
    fireEvent.click(screen.getByRole("radio", { name: /^Oanvända/ }));
    await waitFor(() => expect(tableCalls().at(-1)).toMatchObject({ activity: "unused" }));
    expect(tiles().textContent).toBe(before);
    expect(tileCalls()).toHaveLength(1);
  });

  it("compares the figures with the previous period when asked", async () => {
    renderPage();
    await screen.findByText("Aktiva assistenter");
    fireEvent.click(screen.getByRole("switch", { name: "Jämför med föregående period" }));
    expect(lastAddress().get("compare")).toBe("1");
    await waitFor(() => expect(tileCalls().at(-1)).toMatchObject({ compare: true }));
    // Conversations against 1 500, questions against 3 000, users against 160; not the used ones.
    await waitFor(() =>
      expect(tile("Konversationer")).toMatch(/\+36\s% jämfört med föregående period/)
    );
    expect(tile("Frågor")).toMatch(/\+35\s% jämfört med föregående period/);
    expect(tile("Aktiva användare")).toMatch(/\+15\s% jämfört med föregående period/);
    expect(tile("Aktiva assistenter")).not.toMatch(/jämfört/);
  });

  it("formats the figures in the selected UI language", async () => {
    renderInApp(
      <IntlProvider locale="en" messages={en}>
        <InsightsPage />
      </IntlProvider>,
      { appContext: testAppContext({ permissions: ["insights"] }), route: "/admin/insights" }
    );
    expect(await screen.findByText("2,037")).toBeTruthy();
    expect(screen.getByText("3 of 27")).toBeTruthy();
  });

  it("shows the tokens with the same period to an admin, and nothing of them to others", async () => {
    renderPage("/admin/insights", ["insights", "admin"]);
    const usageLink = await screen.findByRole("link", { name: "Visa tokenanvändning" });
    expect(usageLink.getAttribute("href")).toMatch(/tab=tokens&from=/);
    // A stand-alone link: a touch-sized row of its own (the contract measures it on the screen).
    expect(usageLink.className).toContain("pointer-coarse:min-h-11");
    expect(
      state.calls.find((call) => call.path === "/api/v1/token-usage/")!.query!.end_date
    ).toMatch(/\.999999Z$/);
    cleanup();
    state.calls.length = 0;
    renderPage();
    await screen.findByText("Aktiva assistenter");
    expect(state.calls.some((call) => call.path === "/api/v1/token-usage/")).toBe(false);
    expect(screen.queryByRole("link", { name: "Visa tokenanvändning" })).toBeNull();
  });

  it("lists the assistants and group chats from the API, with their use and where to go", async () => {
    renderPage();
    const table = await screen.findByRole("table", { name: "Assistenter och gruppchattar" });
    expect(tableCalls()[0]).toMatchObject({
      sort: "conversations",
      order: "desc",
      activity: "all",
      compare: false,
      offset: 0,
      limit: 25
    });
    const row = (name: string) =>
      within(table)
        .getAllByRole("row")
        .find((candidate) => within(candidate).queryByText(name))!;

    const assistant = row("Bygglovsassistenten");
    expect(
      within(assistant).getByRole("link", { name: "Bygglovsassistenten" }).getAttribute("href")
    ).toMatch(/^\/admin\/insights\/assistant\/t-1\?from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}$/);
    expect(
      within(assistant).getByRole("img", {
        name: /^58\s%\sanvändare, 36\s%\swidget, 6\s%\sAPI$/
      })
    ).toBeTruthy();
    expect(within(assistant).getByText(/^78\s%$/)).toBeTruthy();

    const groupChat = row("Upphandlingsstöd");
    expect(
      within(groupChat).getByRole("link", { name: "Upphandlingsstöd" }).getAttribute("href")
    ).toMatch(/^\/admin\/insights\/group-chat\/t-2\?/);
    expect(within(groupChat).getByText("Ekonomi, gruppchatt")).toBeTruthy();
    expect(within(groupChat).getByText("Inga betyg")).toBeTruthy();

    // Insights off: use only, and the way to the switch instead of the ratings.
    const off = row("Skolskjutsfrågor");
    expect(within(off).queryByRole("link", { name: "Skolskjutsfrågor" })).toBeNull();
    expect(within(off).getByText("Insikter är avstängda")).toBeTruthy();
    expect(
      within(off).getByRole("link", { name: "Öppna inställningen" }).getAttribute("href")
    ).toBe("/spaces/space-t-3/assistants/t-3/edit?section=publishing#publishing");
  });

  it("sorts, searches, filters and pages the table through the API, in the address", async () => {
    renderPage();
    const table = await screen.findByRole("table", { name: "Assistenter och gruppchattar" });
    expect(screen.getByText("Visar 25 av 27")).toBeTruthy();
    // The filter names how many targets the search finds.
    expect(screen.getByRole("radio", { name: "Alla (27)" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Oanvända (24)" })).toBeTruthy();
    expect(
      within(table)
        .getByRole("columnheader", { name: /Konversationer/ })
        .getAttribute("aria-sort")
    ).toBe("descending");

    // Names start A to Z; a second click flips them. Each change is written in place.
    fireEvent.click(within(table).getByRole("button", { name: "Namn" }));
    expect(lastAddress().get("sort")).toBe("name");
    expect(lastAddress().get("order")).toBe("asc");
    await waitFor(() =>
      expect(tableCalls().at(-1)).toMatchObject({ sort: "name", order: "asc", offset: 0 })
    );
    await waitFor(() =>
      expect(
        within(table).getByRole("columnheader", { name: /Namn/ }).getAttribute("aria-sort")
      ).toBe("ascending")
    );
    fireEvent.click(within(table).getByRole("button", { name: "Namn" }));
    await waitFor(() => expect(tableCalls().at(-1)).toMatchObject({ sort: "name", order: "desc" }));

    // "Visa fler" asks for the next offset and keeps the rows it has.
    fireEvent.click(await screen.findByRole("button", { name: "Visa fler" }));
    await waitFor(() => expect(tableCalls().at(-1)).toMatchObject({ offset: 25 }));
    expect(await screen.findByText("Visar 27 av 27")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Visa fler" })).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: /^Oanvända/ }));
    expect(lastAddress().get("activity")).toBe("unused");
    await waitFor(() =>
      expect(tableCalls().at(-1)).toMatchObject({ activity: "unused", offset: 0 })
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Sök assistent eller gruppchatt" }), {
      target: { value: "  oanvänd 2  " }
    });
    await waitFor(() => expect(lastAddress().get("q")).toBe("oanvänd 2"));
    await waitFor(() => expect(tableCalls().at(-1)).toMatchObject({ q: "oanvänd 2" }));
    expect(await screen.findByText("Visar 6 av 6")).toBeTruthy();
    expect(await screen.findByRole("radio", { name: "Alla (6)" })).toBeTruthy();
    expect(replaceUrl.mock.calls.every(([, options]) => options === undefined)).toBe(true);
  });

  it("starts from its address: the period, the comparison, the filter, the search and the sort", async () => {
    renderPage(
      "/admin/insights?from=2026-09-01&to=2026-09-30&compare=1&activity=unused&q=oanv&sort=name&order=asc"
    );
    await screen.findByRole("table", { name: "Assistenter och gruppchattar" });
    expect(tableCalls()[0]).toMatchObject({
      compare: true,
      activity: "unused",
      q: "oanv",
      sort: "name",
      order: "asc"
    });
    expect(tableCalls()[0]!.start_time).toBe(new Date("2026-09-01T00:00:00").toISOString());
    expect(
      (screen.getByRole("textbox", { name: "Sök assistent eller gruppchatt" }) as HTMLInputElement)
        .value
    ).toBe("oanv");
    expect(screen.getByRole("radio", { name: /^Oanvända/, checked: true })).toBeTruthy();
    expect(
      screen.getByRole("switch", { name: "Jämför med föregående period", checked: true })
    ).toBeTruthy();
    // The way to an assistant's insights carries the period on.
    const link = screen.getAllByRole("link").find((anchor) => anchor.textContent === "Oanvänd 1")!;
    expect(link.getAttribute("href")).toBe(
      "/admin/insights/assistant/u-0?from=2026-09-01&to=2026-09-30&compare=1"
    );
  });

  it("shows the personal spaces as one first row, only in the unfiltered list", async () => {
    renderPage();
    const table = await screen.findByRole("table", { name: "Assistenter och gruppchattar" });
    const firstRow = () => within(table).getAllByRole("row")[1]!;
    const cells = () =>
      within(firstRow())
        .getAllByRole("cell")
        .map((cell) => cell.textContent);
    // Told apart as a summary for assistive technology, and never a link to someone's assistant.
    expect(cells()).toEqual([
      "Personliga assistenter sammanlagt3 assistenter i personliga utrymmen",
      "42",
      "",
      "90",
      "Visas inte för personliga assistenter"
    ]);
    expect(
      within(firstRow()).getByRole("img", { name: /^95\s%\sanvändare, 5\s%\sAPI$/ })
    ).toBeTruthy();
    expect(within(firstRow()).queryByRole("link")).toBeNull();
    // It stays first whatever the sort, and is not counted among the listed targets.
    fireEvent.click(within(table).getByRole("button", { name: "Namn" }));
    await waitFor(() => expect(tableCalls().at(-1)).toMatchObject({ sort: "name" }));
    expect(cells()[0]).toMatch(/^Personliga assistenter/);
    expect(screen.getByText("Visar 25 av 27")).toBeTruthy();

    // A search or "Oanvända" lists some targets: no personal row.
    const search = screen.getByRole("textbox", { name: "Sök assistent eller gruppchatt" });
    fireEvent.change(search, { target: { value: "bygg" } });
    await waitFor(() => expect(tableCalls().at(-1)).toMatchObject({ q: "bygg" }));
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(2));
    expect(within(table).queryByText("Personliga assistenter")).toBeNull();

    fireEvent.change(search, { target: { value: "" } });
    await waitFor(() => expect(within(table).getByText("Personliga assistenter")).toBeTruthy());
    fireEvent.click(screen.getByRole("radio", { name: /^Oanvända/ }));
    await waitFor(() => expect(tableCalls().at(-1)).toMatchObject({ activity: "unused" }));
    expect(await screen.findByText("Visar 24 av 24")).toBeTruthy();
    expect(screen.queryByText("Personliga assistenter")).toBeNull();
  });
});
